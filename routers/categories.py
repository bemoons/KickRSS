import logging
import db
import crud
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("myrss.routers.categories")
router = APIRouter()

@router.get("/feeds/{feed_id}/categories")
def get_feed_categories(feed_id: int):
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
        rows = crud.get_categories_for_feed(conn, feed_id)
        return [dict(r) for r in rows]

@router.get("/categories/{category_id}/entries")
def get_category_entries(
    category_id: int,
    unread: int = Query(1, description="1 = unread only, 0 = all"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.get_entries_for_category(
            conn, 
            category_id, 
            unread_only=(unread == 1), 
            limit=limit, 
            offset=offset
        )
        return [dict(r) for r in rows]

@router.post("/categories/{category_id}/read")
def read_category(category_id: int):
    with db.get_db() as conn:
        ids = crud.mark_category_read(conn, category_id)
        return {"ok": True, "count": len(ids), "ids": ids}
