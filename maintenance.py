import logging
import datetime
import db
import crud
import ai
from config import settings

logger = logging.getLogger(__name__)

def run_maintenance_for_feed(feed_id: int) -> list[dict]:
    """
    Run daily maintenance for a single feed: scan uncategorized entries,
    cluster them, and promote recurring topics to formal categories.
    Returns a list of created categories and moved entry counts.
    """
    promote_threshold = settings.promote_threshold
    logger.info(f"Running maintenance for feed {feed_id} (threshold={promote_threshold})")
    
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed or not feed["enabled"] or not feed["need_classification"]:
            return []
            
        recent_uncategorized = crud.get_recent_uncategorized_entries(conn, feed_id, days=14)
        
    if not recent_uncategorized:
        logger.info(f"No recent uncategorized entries for feed {feed_id}")
        return []
        
    logger.info(f"Found {len(recent_uncategorized)} recent uncategorized entries for feed {feed_id}")
    
    # Format entries for AI
    entries_list = [{"id": row["id"], "title": row["title"]} for row in recent_uncategorized]
    
    # Call AI to identify clusters/topics
    promotions = ai.identify_promotable_topics(entries_list, promote_threshold)
    
    results = []
    if not promotions:
        logger.info(f"AI identified no topics for promotion for feed {feed_id}")
        return []
        
    for promo in promotions:
        category_name = promo.get("category_name", "").strip()
        entry_ids = promo.get("entry_ids", [])
        
        if not category_name or category_name == "未归类" or not entry_ids:
            continue
            
        # Ensure entry_ids is a list of ints and actually belong to the recent list
        valid_ids = []
        allowed_ids = {item["id"] for item in entries_list}
        for eid in entry_ids:
            try:
                int_id = int(eid)
                if int_id in allowed_ids:
                    valid_ids.append(int_id)
            except (ValueError, TypeError):
                continue
                
        if len(valid_ids) < promote_threshold:
            logger.info(f"Skipping promotion of '{category_name}' because valid entry count ({len(valid_ids)}) is below threshold ({promote_threshold})")
            continue
            
        logger.info(f"Promoting category '{category_name}' with {len(valid_ids)} entries for feed {feed_id}")
        
        # Save to DB and move entries
        with db.get_db() as conn:
            cursor = conn.cursor()
            # Check if category exists
            cursor.execute("SELECT id FROM categories WHERE feed_id = ? AND name = ?", (feed_id, category_name))
            row = cursor.fetchone()
            if row:
                category_id = row["id"]
            else:
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                cursor.execute(
                    "INSERT INTO categories (feed_id, name, is_default, created_at) VALUES (?, ?, 0, ?)",
                    (feed_id, category_name, now_str)
                )
                category_id = cursor.lastrowid
                
            moved = crud.move_entries_to_category(conn, valid_ids, category_id)
            
        results.append({
            "category_name": category_name,
            "category_id": category_id,
            "moved_count": moved
        })
        
    try:
        merge_duplicate_categories(feed_id)
    except Exception as me:
        logger.error(f"Failed to merge duplicate categories for feed {feed_id}: {me}", exc_info=True)
        
    try:
        clean_empty_categories(feed_id)
    except Exception as ce:
        logger.error(f"Failed to clean empty categories for feed {feed_id}: {ce}", exc_info=True)
        
    return results

def merge_duplicate_categories(feed_id: int):
    """
    Find duplicate categories for a feed, merge their entries, and delete the duplicate categories.
    """
    logger.info(f"Checking for duplicate categories to merge for feed {feed_id}")
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Get all custom categories (not "未归类") for this feed
        cursor.execute("SELECT id, name FROM categories WHERE feed_id = ? AND is_default = 0", (feed_id,))
        rows = cursor.fetchall()
        
    if len(rows) < 2:
        return
        
    cat_map = {row["name"]: row["id"] for row in rows}
    category_names = list(cat_map.keys())
    
    merges = ai.identify_duplicate_categories(category_names)
    if not merges:
        return
        
    for merge in merges:
        source_name = merge.get("source", "").strip()
        target_name = merge.get("target", "").strip()
        
        if source_name in cat_map and target_name in cat_map:
            source_id = cat_map[source_name]
            target_id = cat_map[target_name]
            
            if source_id == target_id:
                continue
                
            logger.info(f"Merging category '{source_name}' (id={source_id}) into '{target_name}' (id={target_id}) for feed {feed_id}")
            with db.get_db() as conn:
                cursor = conn.cursor()
                # 1. Update entries to new category
                cursor.execute("UPDATE entries SET category_id = ? WHERE category_id = ?", (target_id, source_id))
                # 2. Delete source category
                cursor.execute("DELETE FROM categories WHERE id = ?", (source_id,))
                conn.commit()
                
            # Update local map to reflect the deletion
            del cat_map[source_name]

def clean_empty_categories(feed_id: int):
    """
    Delete custom categories for a feed that have zero entries.
    """
    logger.info(f"Cleaning up empty categories for feed {feed_id}")
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Find custom categories with their entry counts
        cursor.execute("""
            SELECT c.id, c.name, COUNT(e.id) as entry_count
            FROM categories c
            LEFT JOIN entries e ON e.category_id = c.id
            WHERE c.feed_id = ? AND c.is_default = 0
            GROUP BY c.id
        """, (feed_id,))
        rows = cursor.fetchall()
        
        for row in rows:
            if row["entry_count"] == 0:
                logger.info(f"Deleting empty category '{row['name']}' (id={row['id']}) for feed {feed_id}")
                cursor.execute("DELETE FROM categories WHERE id = ?", (row["id"],))
                
        conn.commit()

def build_user_interest_profile():
    """
    聚合近 30 天所有订阅源的 engagement 数据，
    通过 LLM 提炼全局兴趣画像，写入 user_interests 表。
    """
    # 检查功能开关，未开启则跳过
    if not settings.interest_profile_enabled:
        logger.info("Reading profile function is disabled. Skipping LLM interest profile builder.")
        return

    logger.info("Building user interest profile...")
    
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT
                e.id AS entry_id,
                e.title,
                e.attention AS ai_attention,
                e.published_at,
                f.title AS feed_name,
                g.active_dwell_ms,
                g.scrolled_pct,
                g.scrolled_to_bottom,
                g.opened_original,
                g.favorited,
                g.manual_bump
            FROM entries e
            JOIN engagement g ON g.entry_id = e.id
            JOIN feeds f ON f.id = e.feed_id
            WHERE e.fetched_at > datetime('now', '-30 days')
              AND g.opened = 1
        """).fetchall()

    # 冷启动：数据不足时跳过 (少于15篇)
    if len(rows) < 15:
        logger.info(f"Not enough engagement data ({len(rows)} articles < 15). Skipping LLM interest profile builder.")
        return

    # 计算参与度得分
    def engagement_score(row):
        score = 0
        if row['manual_bump'] == 'read':   score += 5
        if row['manual_bump'] == 'glance': score -= 3
        if row['favorited']:               score += 4
        if row['opened_original']:         score += 3
        if row['scrolled_to_bottom']:      score += 2
        
        score += min(row['active_dwell_ms'] / 60000.0, 2.0)
        score += row['scrolled_pct'] * 1.5
        return score

    scored = [(engagement_score(r), r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)

    high = [r for s, r in scored if s >= 4]
    low  = [r for s, r in scored if s <= 0]

    # 取标题列表（各最多 80 条，避免 prompt 过长）
    high_titles = [f"[{r['feed_name']}] {r['title']}" for r in high[:80]]
    low_titles  = [f"[{r['feed_name']}] {r['title']}" for r in low[:80]]

    prompt = f"""你是一个用户阅读行为分析助手。以下是某用户近30天的RSS阅读记录。

## 用户高度关注的文章（长时间阅读、滚动到底、收藏、查看原文、手动提升注意力）
{chr(10).join('- ' + t for t in high_titles) if high_titles else '（数据不足）'}

## 用户较少关注的文章（快速跳过、很少互动）
{chr(10).join('- ' + t for t in low_titles) if low_titles else '（数据不足）'}

请分析并输出以下 JSON（不要输出其他内容）：
{{
  "high_interest": [
    {{"topic": "主题名称（简短，4-10字）", "description": "一句话描述用户在这个主题上的关注点", "strength": "high 或 medium"}},
    ...
  ],
  "low_interest": [
    {{"topic": "主题名称", "description": "一句话描述"}},
    ...
  ],
  "attention_guide": "一段自然语言，50-120字，概括用户的整体阅读倾向，供分类器参考。格式示例：'用户高度关注XX和XX方向，尤其是涉及XX的内容应标为read；对XX and XX类内容兴趣较低，可标为glance。'",
  "concentration_note": "如果 high_interest 中超过半数主题属于同一领域，输出一句温和的提醒（20-40字），否则设为 null"
}}

要求：
- high_interest 提取 3-8 个主题，按关注强度从高到低排列
- low_interest 提取 2-5 个主题
- 主题应跨订阅源归纳，不要按订阅源罗列
- 如果某类文章高参与和低参与中都有，说明用户对该主题的子方向有选择性，请在 description 中体现
- attention_guide 必须具体到可操作，不要说"用户关注科技"这种空话
"""

    logger.info("Calling LLM to extract interest profile...")
    messages = [
        {"role": "system", "content": "You are a helpful reading behavior analyst."},
        {"role": "user", "content": prompt}
    ]
    
    ai_config = settings.get_ai_config("profile")
    ai_config["max_tokens"] = 1500
    
    try:
        response_text = ai.call_chat_completion(ai_config, messages, response_format_json=True)
    except Exception as e:
        logger.error(f"LLM call failed for interest profile builder: {e}", exc_info=True)
        return

    import json
    try:
        parsed = json.loads(response_text)
    except Exception as e:
        logger.error(f"Failed to parse interest profile LLM response as JSON: {e}\nResponse: {response_text}")
        return

    # Post-processing: match entries back to topics
    all_topics = parsed.get('high_interest', []) + parsed.get('low_interest', [])
    for topic_item in all_topics:
        topic_name = topic_item.get('topic', '')
        matched_ids = []
        
        # Split topic name into keywords (chars of length >= 2) for fuzzy lookup
        keywords = [topic_name[i:i+2] for i in range(len(topic_name) - 1)]
        keywords = [kw for kw in keywords if len(kw.strip()) >= 2]
        if not keywords:
            keywords = [topic_name]
            
        for r in rows:
            title = r['title']
            feed = r['feed_name']
            if any(kw in title or kw in feed for kw in keywords):
                matched_ids.append(r['entry_id'])
                
        topic_item['entry_ids'] = matched_ids[:20]  # Limit to top 20 entries

    # Write to database
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO user_interests (snapshot_date, total_articles, high_engagement,
                low_engagement, topics_json, prompt_text, generated_at)
            VALUES (date('now'), ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(snapshot_date) DO UPDATE SET
                total_articles = excluded.total_articles,
                high_engagement = excluded.high_engagement,
                low_engagement = excluded.low_engagement,
                topics_json = excluded.topics_json,
                prompt_text = excluded.prompt_text,
                generated_at = excluded.generated_at
        """, (len(rows), len(high), len(low),
              json.dumps(parsed, ensure_ascii=False),
              parsed.get('attention_guide', '')))
        
    logger.info("Successfully updated user interest profile snapshot in database.")

def run_all_feeds_maintenance() -> dict:
    """
    Run daily maintenance for all enabled feeds.
    """
    logger.info("Running daily maintenance job for all feeds")
    report = {}
    
    # 1. Reset classification for all uncategorized entries
    with db.get_db() as conn:
        crud.reset_uncategorized_entries_classification(conn)
        feeds = crud.list_feeds(conn)
        
    # 2. Re-classify those entries first so they map to existing drawers if possible
    from classifier import classify_feed_entries
    for feed in feeds:
        if feed["enabled"]:
            try:
                classify_feed_entries(feed["id"])
            except Exception as e:
                logger.error(f"Pre-maintenance classification failed for feed {feed['id']}: {e}")
                
    # 3. Perform topic promotion, merging and cleaning
    for feed in feeds:
        if not feed["enabled"]:
            continue
        try:
            res = run_maintenance_for_feed(feed["id"])
            if res:
                report[feed["id"]] = res
        except Exception as e:
            logger.error(f"Maintenance job failed for feed {feed['id']}: {e}", exc_info=True)
            
    # 4. Generate user interest profile
    try:
        build_user_interest_profile()
    except Exception as e:
        logger.error(f"Failed to build user interest profile during maintenance: {e}", exc_info=True)
        
    # 5. Clean up old user interests snapshot records (older than 90 days)
    try:
        with db.get_db() as conn:
            conn.execute("DELETE FROM user_interests WHERE snapshot_date < date('now', '-90 days')")
        logger.info("Successfully cleaned up old user interests snapshot records.")
    except Exception as e:
        logger.error(f"Failed to clean up old user interests snapshots: {e}", exc_info=True)
        
    return report
