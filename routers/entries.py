import logging
import db
import crud
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import services.entry_service as entry_service
import services.ai_service as ai_service

logger = logging.getLogger("myrss.routers.entries")
router = APIRouter()

# Pydantic schemas
class ReadEntries(BaseModel):
    ids: List[int]

class ChatRequest(BaseModel):
    message: str

class AttentionRequest(BaseModel):
    attention: str

class TranslateParagraphRequest(BaseModel):
    para_index: int
    text: str

class EngagementRequest(BaseModel):
    active_dwell_ms: int
    scrolled_pct: float
    opened_original: bool

@router.get("/feeds/{feed_id}/entries")
def get_feed_entries(
    feed_id: int,
    unread: int = Query(1, description="1 = unread only, 0 = all"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.get_entries_for_feed(
            conn, 
            feed_id, 
            unread_only=(unread == 1), 
            limit=limit, 
            offset=offset
        )
        feed = crud.get_feed_by_id(conn, feed_id)
        feed_title = feed["title"] if feed else "Unknown"
        
        result = []
        for r in rows:
            d = dict(r)
            d["feed_title"] = feed_title
            result.append(d)
        return result

@router.get("/search")
def search_entries(
    q: str,
    unread: int = Query(0, description="1 = unread only, 0 = all"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.search_entries(conn, q, unread_only=(unread == 1), limit=limit, offset=offset)
        
        result = []
        feeds_cache = {}
        for r in rows:
            d = dict(r)
            feed_id = d["feed_id"]
            if feed_id not in feeds_cache:
                feed = crud.get_feed_by_id(conn, feed_id)
                feeds_cache[feed_id] = feed["title"] if feed else "Unknown"
            d["feed_title"] = feeds_cache[feed_id]
            result.append(d)
        return result

@router.get("/entries/{entry_id}/fulltext")
def get_entry_fulltext(entry_id: int):
    return entry_service.get_entry_fulltext(entry_id)

@router.post("/entries/{entry_id}/read")
def read_single_entry(entry_id: int):
    entry_service.read_single_entry(entry_id)
    return {"ok": True}

@router.post("/entries/{entry_id}/unread")
def unread_single_entry(entry_id: int):
    entry_service.unread_single_entry(entry_id)
    return {"ok": True}

@router.post("/entries/{entry_id}/attention")
def update_entry_attention(entry_id: int, req: AttentionRequest):
    entry_service.update_entry_attention(entry_id, req.attention)
    return {"ok": True}

@router.get("/entries/unread")
def get_unread_entries_api(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.get_unread_entries(conn, limit=limit, offset=offset)
        return [dict(r) for r in rows]

@router.get("/entries/starred")
def get_starred_entries(
    unread: int = Query(0, description="1 = unread only, 0 = all"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.get_starred_entries(
            conn, 
            unread_only=(unread == 1), 
            limit=limit, 
            offset=offset
        )
        result = []
        feeds_cache = {}
        for r in rows:
            d = dict(r)
            feed_id = d["feed_id"]
            if feed_id not in feeds_cache:
                feed = crud.get_feed_by_id(conn, feed_id)
                feeds_cache[feed_id] = feed["title"] if feed else "Unknown"
            d["feed_title"] = feeds_cache[feed_id]
            result.append(d)
        return result

@router.get("/entries/starred/count")
def get_starred_count():
    with db.get_db() as conn:
        return crud.get_starred_entries_count(conn)

@router.post("/entries/{entry_id}/star")
def star_entry(entry_id: int):
    entry_service.star_entry(entry_id)
    return {"ok": True}

@router.post("/entries/{entry_id}/unstar")
def unstar_entry(entry_id: int):
    entry_service.unstar_entry(entry_id)
    return {"ok": True}

@router.post("/entries/read")
def read_multiple_entries(req: ReadEntries):
    with db.get_db() as conn:
        count = crud.mark_entries_read(conn, req.ids)
        return {"ok": True, "count": count, "ids": req.ids}

@router.post("/feeds/{feed_id}/read")
def read_feed(feed_id: int):
    with db.get_db() as conn:
        ids = crud.mark_feed_read(conn, feed_id)
        return {"ok": True, "count": len(ids), "ids": ids}

@router.post("/entries/unread")
def unread_multiple_entries(req: ReadEntries):
    with db.get_db() as conn:
        count = crud.mark_entries_unread(conn, req.ids)
        return {"ok": True, "count": count}

@router.get("/entries/{entry_id}/summary")
def get_entry_summary(
    entry_id: int, 
    stream: Optional[bool] = None, 
    force: Optional[bool] = None,
    cache_only: Optional[bool] = None
):
    is_stream, result = ai_service.get_entry_summary(entry_id, stream, force, cache_only=bool(cache_only))
    if is_stream:
        return StreamingResponse(result, media_type="text/event-stream")
    else:
        return result

@router.get("/entries/{entry_id}/translate")
def get_entry_translation(entry_id: int, force: Optional[bool] = None):
    return ai_service.get_entry_translation(entry_id, force)

@router.post("/entries/{entry_id}/translate_paragraph")
def translate_entry_paragraph(entry_id: int, req: TranslateParagraphRequest):
    return ai_service.translate_entry_paragraph(entry_id, req.para_index, req.text)

@router.post("/entries/{entry_id}/chat")
def chat_with_entry(entry_id: int, req: ChatRequest, stream: Optional[bool] = None):
    is_stream, result = ai_service.chat_with_entry(entry_id, req.message, stream)
    if is_stream:
        return StreamingResponse(result, media_type="text/event-stream")
    else:
        return result

@router.get("/entries/{entry_id}/chat")
def get_entry_chat_history(entry_id: int):
    with db.get_db() as conn:
        rows = crud.get_chat_history(conn, entry_id)
        return [dict(r) for r in rows]

@router.delete("/chat-messages/{message_id}")
def delete_chat_message(message_id: int):
    with db.get_db() as conn:
        success = crud.delete_chat_message(conn, message_id)
        if not success:
            raise HTTPException(status_code=404, detail="Message not found")
        return {"ok": True}

@router.post("/entries/{entry_id}/engagement")
def record_engagement(entry_id: int, req: EngagementRequest):
    return entry_service.record_engagement(entry_id, req.active_dwell_ms, req.scrolled_pct, req.opened_original)

@router.post("/entries/{entry_id}/favorite")
def toggle_favorite(entry_id: int):
    return entry_service.toggle_favorite(entry_id)

@router.get("/entries/notes")
def get_notes_entries(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.get_notes_entries(conn, limit=limit, offset=offset)
        result = []
        feeds_cache = {}
        for r in rows:
            d = dict(r)
            feed_id = d["feed_id"]
            if feed_id not in feeds_cache:
                feed = crud.get_feed_by_id(conn, feed_id)
                feeds_cache[feed_id] = feed["title"] if feed else "Unknown"
            d["feed_title"] = feeds_cache[feed_id]
            result.append(d)
        return result

@router.get("/entries/notes/count")
def get_notes_count():
    with db.get_db() as conn:
        return crud.get_notes_entries_count(conn)
