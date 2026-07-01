import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from config import settings
from db import get_db
import crud
import ai
from ingester import FeedparserIngester
from maintenance import run_all_feeds_maintenance

logger = logging.getLogger(__name__)

# Single global scheduler instance
scheduler = BackgroundScheduler()

def ensure_feed_seeded(feed_id: int) -> bool:
    """
    Check if the feed is seeded. If not, and classification is enabled,
    try to seed categories using recent entries.
    Returns True if successfully seeded or already seeded.
    """
    with get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            return False
        if not feed["need_classification"]:
            if not feed["seeded"]:
                cursor = conn.cursor()
                cursor.execute("UPDATE feeds SET seeded = 1 WHERE id = ?", (feed_id,))
                conn.commit()
            return True
        if feed["seeded"]:
            return True
            
        # Try to gather recent titles to generate seed categories
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM entries WHERE feed_id = ? ORDER BY published_at DESC LIMIT 100", (feed_id,))
        titles = [r["title"] for r in cursor.fetchall() if r["title"]]
        
    if not titles:
        # No entries yet to seed from
        return False
        
    logger.info(f"Feed {feed_id} is not seeded. Attempting to generate seed categories with {len(titles)} articles.")
    try:
        seed_categories = ai.generate_seed_categories(titles)
        if seed_categories:
            logger.info(f"Successfully generated seed categories for feed {feed_id}: {seed_categories}")
            with get_db() as conn:
                crud.save_categories(conn, feed_id, seed_categories)
                default_cat_id = crud.get_default_category(conn, feed_id)
                cursor = conn.cursor()
                # Reset previously classified entries in default category back to NULL
                # so the classifier will re-classify them into the newly seeded categories.
                cursor.execute(
                    "UPDATE entries SET category_id = ?, classified_at = NULL WHERE feed_id = ? AND category_id = ?",
                    (default_cat_id, feed_id, default_cat_id)
                )
                cursor.execute("UPDATE feeds SET seeded = 1 WHERE id = ?", (feed_id,))
                conn.commit()
            return True
        else:
            logger.warning(f"AI generated empty seed categories for feed {feed_id} (possibly LLM not configured). Will retry later.")
            return False
    except Exception as e:
        logger.error(f"Failed to auto-seed categories for feed {feed_id}: {e}", exc_info=True)
        return False

def refresh_single_feed(feed_id: int, force: bool = False, skip_classification: bool = False) -> tuple[int, int]:
    """
    Refresh a single feed by ID.
    Returns a tuple of (fetched_entries_count, new_entries_count).
    """
    with get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed or not feed["enabled"]:
            return 0, 0
        
        url = feed["url"]
        etag = None if force else feed["etag"]
        last_modified = None if force else feed["last_modified"]
        
    logger.info(f"Refreshing feed {feed_id}: {url}")
    
    ingester = FeedparserIngester()
    try:
        result = ingester.fetch_new(url, etag, last_modified)
    except Exception as e:
        logger.error(f"Failed to fetch feed {feed_id} ({url}): {e}", exc_info=True)
        raise
        
    if result.not_modified:
        # Check if the feed needs seeding even if there were no new entries
        try:
            ensure_feed_seeded(feed_id)
        except Exception as e:
            logger.error(f"Failed to ensure feed {feed_id} is seeded: {e}", exc_info=True)
            
        with get_db() as conn:
            crud.update_feed_fetch_status(conn, feed_id, etag, last_modified)
        return 0, 0
        
    fetched_count = len(result.entries)
    new_count = 0
    
    if fetched_count > 0:
        with get_db() as conn:
            default_cat_id = crud.get_default_category(conn, feed_id)
            new_count = crud.save_entries(conn, feed_id, result.entries, default_cat_id)
            crud.update_feed_fetch_status(conn, feed_id, result.etag, result.last_modified)
            
        logger.info(f"Feed {feed_id} refreshed: {fetched_count} fetched, {new_count} new entries saved.")
    else:
        with get_db() as conn:
            crud.update_feed_fetch_status(conn, feed_id, result.etag, result.last_modified)
            
    # Ensure feed is seeded if it wasn't already
    try:
        ensure_feed_seeded(feed_id)
    except Exception as e:
        logger.error(f"Failed to ensure feed {feed_id} is seeded: {e}", exc_info=True)
        
    # Classify any unclassified entries for this feed (either new or reset/fallback ones)
    if not skip_classification:
        try:
            from classifier import classify_feed_entries
            classify_feed_entries(feed_id)
        except Exception as e:
            logger.error(f"Failed to classify entries for feed {feed_id}: {e}", exc_info=True)
            
    return fetched_count, new_count

def refresh_all_feeds() -> tuple[int, int]:
    """
    Refresh all enabled feeds in the database.
    Isolates errors for individual feeds so one failing feed does not block others.
    Returns a tuple of (processed_feeds_count, total_new_entries_count).
    """
    processed_count = 0
    total_new = 0
    
    with get_db() as conn:
        feeds = crud.list_feeds(conn)
        
    for feed in feeds:
        if not feed["enabled"]:
            continue
        try:
            _, new_count = refresh_single_feed(feed["id"])
            total_new += new_count
            processed_count += 1
        except Exception as e:
            logger.error(f"Error during scheduled refresh of feed {feed['id']}: {e}")
            
    return processed_count, total_new

def start_scheduler():
    if not scheduler.running:
        interval = settings.fetch_interval_minutes
        logger.info(f"Starting background scheduler with {interval} minutes interval")
        
        # 1. Scheduled RSS feed refresh trigger
        scheduler.add_job(
            refresh_all_feeds,
            trigger=IntervalTrigger(minutes=interval),
            id="refresh_all_feeds_job",
            replace_existing=True
        )
        
        # 2. Scheduled daily maintenance trigger (runs at 3:00 AM daily)
        scheduler.add_job(
            run_all_feeds_maintenance,
            trigger=CronTrigger(hour=3, minute=0),
            id="daily_maintenance_job",
            replace_existing=True
        )
        
        scheduler.start()

def shutdown_scheduler():
    if scheduler.running:
        logger.info("Shutting down background scheduler")
        scheduler.shutdown()

def reschedule_refresh_job(minutes: int):
    """
    Reschedule the RSS feed refresh job with a new interval in minutes.
    """
    if scheduler.running:
        try:
            scheduler.reschedule_job(
                job_id="refresh_all_feeds_job",
                trigger=IntervalTrigger(minutes=minutes)
            )
            logger.info(f"Rescheduled refresh job 'refresh_all_feeds_job' to {minutes} minutes interval.")
        except Exception as e:
            logger.error(f"Failed to reschedule job: {e}")

