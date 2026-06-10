import logging
import db
import crud
import opml
import ai
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, BackgroundTasks, UploadFile
from fastapi.responses import Response
from ingester import FeedparserIngester
from classifier import classify_feed_entries

logger = logging.getLogger("myrss.feed_service")

def async_cold_start_feed(feed_id: int):
    logger.info(f"Starting async cold start for feed {feed_id}")
    try:
        with db.get_db() as conn:
            feed = crud.get_feed_by_id(conn, feed_id)
            if not feed:
                logger.error(f"Feed {feed_id} not found for cold start")
                return
            url = feed["url"]
            need_classify = feed["need_classification"]
            
        ingester = FeedparserIngester()
        result = ingester.fetch_new(url)
        
        # 1. Generate seed categories using AI from titles
        titles = [e.title for e in result.entries if e.title]
        logger.info(f"Seeding categories for feed {feed_id} with {len(titles)} articles")
        seed_categories = []
        if titles and need_classify:
            try:
                seed_categories = ai.generate_seed_categories(titles)
                logger.info(f"AI generated categories: {seed_categories}")
            except Exception as ae:
                logger.error(f"AI category generation failed: {ae}, using fallbacks.")
        
        seeded_val = 1 if (seed_categories or not need_classify) else 0
        with db.get_db() as conn:
            if seed_categories:
                crud.save_categories(conn, feed_id, seed_categories)
                
            title = result.feed_title or feed["title"]
            site_url = result.site_url or feed["site_url"]
            
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE feeds SET title = ?, site_url = ?, seeded = ? WHERE id = ?",
                (title, site_url, seeded_val, feed_id)
            )
            
            default_cat_id = crud.get_default_category(conn, feed_id)
            new_count = crud.save_entries(conn, feed_id, result.entries, default_cat_id)
            crud.update_feed_fetch_status(conn, feed_id, result.etag, result.last_modified)
            
            logger.info(f"Cold start entries stored for feed {feed_id}: {new_count} entries saved.")
            
        if new_count > 0:
            try:
                classify_feed_entries(feed_id)
            except Exception as ce:
                logger.error(f"Classification failed during cold start: {ce}", exc_info=True)
                
    except Exception as e:
        logger.error(f"Cold start failed for feed {feed_id}: {e}", exc_info=True)

def sync_reset_feed_categories_step1(feed_id: int):
    logger.info(f"Starting sync category reset step 1 (seeding) for feed {feed_id}")
    try:
        with db.get_db() as conn:
            feed = crud.get_feed_by_id(conn, feed_id)
            need_classify = feed["need_classification"] if feed else 1
            
            default_cat_id = crud.get_default_category(conn, feed_id)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM categories WHERE feed_id = ? AND is_default = 0", (feed_id,))
            cursor.execute("UPDATE entries SET category_id = ?, classified_at = NULL WHERE feed_id = ?", (default_cat_id, feed_id))
            
            titles = []
            if need_classify:
                cursor.execute("SELECT title FROM entries WHERE feed_id = ? ORDER BY published_at DESC LIMIT 100", (feed_id,))
                titles = [r["title"] for r in cursor.fetchall() if r["title"]]
            conn.commit()
            
        seed_categories = []
        if titles and need_classify:
            try:
                seed_categories = ai.generate_seed_categories(titles)
                logger.info(f"AI generated categories for reset of feed {feed_id}: {seed_categories}")
            except Exception as ae:
                logger.error(f"AI category generation failed during reset of feed {feed_id}: {ae}")
                
        seeded_val = 1 if (seed_categories or not need_classify) else 0
        with db.get_db() as conn:
            if seed_categories and need_classify:
                crud.save_categories(conn, feed_id, seed_categories)
                
            cursor = conn.cursor()
            cursor.execute("UPDATE feeds SET seeded = ? WHERE id = ?", (seeded_val, feed_id))
            conn.commit()
            
    except Exception as e:
        logger.error(f"Failed to clear and seed categories for feed {feed_id}: {e}", exc_info=True)
        raise e

def async_reset_feed_categories(feed_id: int):
    logger.info(f"Starting async category reset for feed {feed_id}")
    try:
        sync_reset_feed_categories_step1(feed_id)
        classify_feed_entries(feed_id)
        logger.info(f"Finished category reset and classification for feed {feed_id}")
    except Exception as e:
        logger.error(f"Failed to reset categories for feed {feed_id}: {e}", exc_info=True)

def add_feed(url: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid feed URL scheme (must be http or https)")
        
    with db.get_db() as conn:
        existing = crud.get_feed_by_url(conn, url)
        if existing:
            return dict(existing)
            
        feed_id = crud.add_feed(conn, url, title=url)
        feed_row = crud.get_feed_by_id(conn, feed_id)
        feed_dict = dict(feed_row) if feed_row else {}
        
    background_tasks.add_task(async_cold_start_feed, feed_id)
    return feed_dict

def update_feed(feed_id: int, title: Optional[str], enabled: Optional[bool], need_classification: Optional[bool]) -> Dict[str, Any]:
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
        if title is not None:
            crud.update_feed_title(conn, feed_id, title.strip())
        if enabled is not None:
            crud.update_feed_enabled(conn, feed_id, enabled)
        if need_classification is not None:
            crud.update_feed_need_classification(conn, feed_id, need_classification)
        updated = crud.get_feed_by_id(conn, feed_id)
        return dict(updated)

def delete_feed(feed_id: int) -> bool:
    with db.get_db() as conn:
        success = crud.delete_feed(conn, feed_id)
        if not success:
            raise HTTPException(status_code=404, detail="Feed not found")
        return True

async def import_opml(file: UploadFile, background_tasks: BackgroundTasks) -> int:
    try:
        content = await file.read()
        feeds = opml.parse_opml(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse OPML file: {str(e)}")

    added_count = 0
    with db.get_db() as conn:
        for f in feeds:
            existing = crud.get_feed_by_url(conn, f["url"])
            if not existing:
                feed_id = crud.add_feed(conn, f["url"], f["title"], f["site_url"])
                background_tasks.add_task(async_cold_start_feed, feed_id)
                added_count += 1
    return added_count

def export_opml() -> Response:
    with db.get_db() as conn:
        feeds = crud.list_feeds(conn)
        feed_dicts = [dict(f) for f in feeds]
        
    opml_str = opml.generate_opml(feed_dicts)
    return Response(
        content=opml_str,
        media_type="application/xml",
        headers={
            "Content-Disposition": "attachment; filename=kickrss_subscriptions.opml"
        }
    )

def reset_all_feeds_categories(background_tasks: BackgroundTasks) -> int:
    with db.get_db() as conn:
        feeds = crud.list_feeds(conn)
        
    for feed in feeds:
        if feed["enabled"]:
            background_tasks.add_task(async_reset_feed_categories, feed["id"])
            
    return len(feeds)

def reset_single_feed_categories(feed_id: int, background_tasks: BackgroundTasks):
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
            
    sync_reset_feed_categories_step1(feed_id)
    background_tasks.add_task(classify_feed_entries, feed_id)
