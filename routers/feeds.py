import logging
import db
import crud
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Depends
from pydantic import BaseModel
import services.feed_service as feed_service
from scheduler import refresh_all_feeds

logger = logging.getLogger("myrss.routers.feeds")
router = APIRouter()

class FeedCreate(BaseModel):
    url: str

class FeedUpdate(BaseModel):
    title: Optional[str] = None
    enabled: Optional[bool] = None
    need_classification: Optional[bool] = None

@router.get("/feeds")
def get_feeds():
    with db.get_db() as conn:
        rows = crud.list_feeds(conn)
        return [dict(r) for r in rows]

@router.post("/feeds")
def add_feed(feed_in: FeedCreate, background_tasks: BackgroundTasks):
    return feed_service.add_feed(feed_in.url, background_tasks)

@router.put("/feeds/{feed_id}")
def update_feed(feed_id: int, feed_in: FeedUpdate):
    return feed_service.update_feed(feed_id, feed_in.title, feed_in.enabled, feed_in.need_classification)

@router.delete("/feeds/{feed_id}")
def delete_feed(feed_id: int):
    feed_service.delete_feed(feed_id)
    return {"ok": True}

@router.post("/refresh")
def force_refresh_all():
    processed, total_new = refresh_all_feeds()
    return {"ok": True, "fetched": processed, "new_entries": total_new}

@router.post("/import/opml")
async def import_opml(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    added_count = await feed_service.import_opml(file, background_tasks)
    return {"ok": True, "added": added_count}

@router.get("/export/opml")
def export_opml():
    return feed_service.export_opml()

@router.post("/feeds/reset-categories")
def reset_all_feeds_categories(background_tasks: BackgroundTasks):
    count = feed_service.reset_all_feeds_categories(background_tasks)
    return {"ok": True, "message": f"Triggered category reset for {count} feeds."}

@router.post("/feeds/{feed_id}/reset-categories")
def reset_single_feed_categories(feed_id: int, background_tasks: BackgroundTasks):
    feed_service.reset_single_feed_categories(feed_id, background_tasks)
    return {"ok": True, "message": f"Category reset and seeding completed for feed {feed_id}. Classification enqueued in background."}

@router.post("/maintenance")
def trigger_maintenance():
    from maintenance import run_all_feeds_maintenance
    report = run_all_feeds_maintenance()
    return {"ok": True, "result": report}
