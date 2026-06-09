import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from config import settings
from db import get_db
import crud
from ingester import FeedparserIngester
from maintenance import run_all_feeds_maintenance

logger = logging.getLogger(__name__)

# Single global scheduler instance
scheduler = BackgroundScheduler()

def refresh_single_feed(feed_id: int) -> tuple[int, int]:
    """
    Refresh a single feed by ID.
    Returns a tuple of (fetched_entries_count, new_entries_count).
    """
    with get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed or not feed["enabled"]:
            return 0, 0
        
        url = feed["url"]
        etag = feed["etag"]
        last_modified = feed["last_modified"]
        
    logger.info(f"Refreshing feed {feed_id}: {url}")
    
    ingester = FeedparserIngester()
    try:
        result = ingester.fetch_new(url, etag, last_modified)
    except Exception as e:
        logger.error(f"Failed to fetch feed {feed_id} ({url}): {e}", exc_info=True)
        raise
        
    if result.not_modified:
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
            
    # Classify any unclassified entries for this feed (either new or reset/fallback ones)
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

