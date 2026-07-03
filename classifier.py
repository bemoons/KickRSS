import logging
import threading
from typing import List, Dict, Any
import db
import crud
import ai
from config import settings

logger = logging.getLogger(__name__)

# Global locks and sets to prevent concurrent classification or pregeneration for the same feed
classification_lock = threading.Lock()
running_classifications = set()

pregen_lock = threading.Lock()
running_pregens = set()

def classify_feed_entries(feed_id: int):
    """
    Classify all unclassified entries for a specific feed in batches.
    """
    with classification_lock:
        if feed_id in running_classifications:
            logger.info(f"Classification for feed {feed_id} is already in progress. Skipping duplicate run.")
            return
        running_classifications.add(feed_id)

    try:
        _classify_feed_entries_impl(feed_id)
    finally:
        with classification_lock:
            running_classifications.discard(feed_id)

def _classify_feed_entries_impl(feed_id: int):
    logger.info(f"Starting classification for feed {feed_id}")
    
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed or not feed["need_classification"]:
            logger.info(f"Feed {feed_id} has AI classification disabled, skipping.")
            return
            
    classify_cfg = settings.get_ai_config("classify")
    batch_size = classify_cfg.get("batch_size", 25)
    
    with db.get_db() as conn:
        # Get all categories for this feed to build name mapping
        categories = crud.get_categories_for_feed(conn, feed_id)
        if not categories:
            logger.warning(f"No categories found for feed {feed_id}, skipping classification.")
            return
            
        default_cat_id = None
        category_map = {} # lowercase name -> id
        allowed_category_names = []
        
        for cat in categories:
            cat_name = cat["name"]
            cat_id = cat["id"]
            category_map[cat_name.lower()] = cat_id
            allowed_category_names.append(cat_name)
            if cat["is_default"]:
                default_cat_id = cat_id
                
        if default_cat_id is None:
            # Fallback if no default category exists yet
            default_cat_id = crud.get_default_category(conn, feed_id)
            category_map["未归类"] = default_cat_id
            allowed_category_names.append("未归类")

        # Get all unclassified entries
        unclassified = crud.get_unclassified_entries(conn, feed_id)
        if not unclassified:
            logger.info(f"No unclassified entries for feed {feed_id}")
            return
            
        logger.info(f"Found {len(unclassified)} unclassified entries for feed {feed_id}")
        
        # Batching entries
        unclassified_list = [dict(row) for row in unclassified]
        for i in range(0, len(unclassified_list), batch_size):
            batch = unclassified_list[i : i + batch_size]
            batch_entries = [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "summary": item["raw_content"] or ""
                }
                for item in batch
            ]
            
            logger.info(f"Classifying batch of {len(batch_entries)} entries (index {i} to {i + len(batch_entries)})")
            
            # Fetch user reading preferences if enabled
            interest_prompt = ""
            if settings.interest_profile_enabled:
                latest_interest = crud.get_latest_user_interest(conn)
                if latest_interest and latest_interest["prompt_text"]:
                    interest_prompt = latest_interest["prompt_text"]

            # Call AI batch classifier
            results = ai.classify_entries_batch(allowed_category_names, batch_entries, interest_prompt)
            
            # Map results to a dict for easy lookup
            results_map = {res["id"]: res for res in results if "id" in res}
            
            # Process each item in the batch (ensuring all get updated even if AI missed them)
            for item in batch_entries:
                entry_id = item["id"]
                res = results_map.get(entry_id)
                
                category_id = default_cat_id
                attention = "skim"
                
                if res:
                    ai_cat = res.get("category", "")
                    ai_att = res.get("attention", "")
                    
                    # Resolve category ID
                    if ai_cat and ai_cat.lower() in category_map:
                        category_id = category_map[ai_cat.lower()]
                    
                    # Resolve attention
                    if ai_att in ["read", "skim", "glance"]:
                        attention = ai_att
                else:
                    logger.warning(f"AI classification missing result for entry {entry_id}, falling back.")
                    
                # Update DB
                crud.update_entry_classification(conn, entry_id, category_id, attention)
                
    logger.info(f"Completed classification for feed {feed_id}")
    
    # Trigger pregeneration of summaries if configured
    try:
        pregenerate_summaries_for_feed(feed_id)
    except Exception as e:
        logger.error(f"Failed to pregenerate summaries for feed {feed_id}: {e}", exc_info=True)

def pregenerate_summaries_for_feed(feed_id: int):
    """
    Pregenerates summaries for entries in this feed that are marked as 'read'
    and have fulltext already available, and caches them.
    """
    ai_cfg = settings.get_ai_config("summary")
    if not ai_cfg.get("pregenerate"):
        return

    with pregen_lock:
        if feed_id in running_pregens:
            logger.info(f"Summary pregeneration for feed {feed_id} is already in progress. Skipping duplicate run.")
            return
        running_pregens.add(feed_id)

    try:
        _pregenerate_summaries_for_feed_impl(feed_id, ai_cfg)
    finally:
        with pregen_lock:
            running_pregens.discard(feed_id)

def _pregenerate_summaries_for_feed_impl(feed_id: int, ai_cfg: dict):
    logger.info(f"Checking for summaries to pregenerate for feed {feed_id}")
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.id, e.title, e.url, f.content as fulltext_content
            FROM entries e
            JOIN fulltext f ON f.entry_id = e.id
            LEFT JOIN summaries s ON s.entry_id = e.id
            WHERE e.feed_id = ? AND e.attention = 'read' AND e.fulltext_ready = 1 
              AND f.status = 'ok' AND s.entry_id IS NULL
            ORDER BY e.published_at DESC
            LIMIT 5
        """, (feed_id,))
        rows = cursor.fetchall()
        
    if not rows:
        return
        
    logger.info(f"Pregenerating summaries for {len(rows)} entries in feed {feed_id}")
    for row in rows:
        try:
            entry_id = row["id"]
            title = row["title"]
            url = row["url"]
            content = row["fulltext_content"]
            
            # Generate summary synchronously (in background task)
            raw_summary = ai.generate_summary_sync(title, url, content)
            summary_text, clickbait = ai.parse_ai_summary_response(raw_summary)
            
            # Save to database
            with db.get_db() as conn:
                crud.save_summary(conn, entry_id, summary_text, clickbait, ai_cfg["model"])
                
            logger.info(f"Pregenerated summary for entry {entry_id}")
        except Exception as e:
            logger.error(f"Failed to pregenerate summary for entry {row['id']}: {e}", exc_info=True)
