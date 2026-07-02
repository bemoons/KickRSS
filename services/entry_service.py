import logging
import db
import crud
import ai
from config import settings
from typing import List, Optional, Dict, Any
from fastapi import HTTPException

logger = logging.getLogger("myrss.entry_service")

def get_entry_fulltext(entry_id: int) -> Dict[str, Any]:
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        
        has_summary = False
        summary_row = crud.get_entry_summary(conn, entry_id)
        if summary_row and summary_row["content"] and summary_row["content"].strip():
            has_summary = True
        
        # 1. Try reading from cached fulltext (Fast Path)
        row = crud.get_entry_fulltext(conn, entry_id)
        if row and (row["content"] or "").strip() and (row["status"] == "ok" or row["status"] == "video"):
            clean_len = ai.estimate_clean_text_length(row["content"] or "")
            return {"content": row["content"], "status": row["status"], "has_summary": has_summary, "clean_char_count": clean_len}
            
        min_chars = settings.min_text_chars
        
        # 2. Prioritize raw_content in the database if it is already present and long enough!
        if (entry["raw_content"] or "").strip():
            clean_content = crud.clean_html(entry["raw_content"])
            if len(clean_content) >= min_chars:
                crud.save_fulltext(conn, entry_id, clean_content, "ok", "feed")
                clean_len = ai.estimate_clean_text_length(clean_content)
                return {"content": clean_content, "status": "ok", "has_summary": has_summary, "clean_char_count": clean_len}
            
    # 3. Cache missed or too short. Try self-healing: trigger single feed refresh (forcing reload)
    try:
        from scheduler import refresh_single_feed
        # Force refresh the feed to pull down updated XML and run self-healing entries updates
        refresh_single_feed(entry["feed_id"], force=True, skip_classification=True)
    except Exception as e:
        logger.warning(f"Forced refresh for feed {entry['feed_id']} failed during self-healing: {e}")

    # Re-read the database to check if feed refresh successfully updated this entry
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        row = crud.get_entry_fulltext(conn, entry_id)
        if row and (row["content"] or "").strip() and (row["status"] == "ok" or row["status"] == "video"):
            clean_len = ai.estimate_clean_text_length(row["content"] or "")
            return {"content": row["content"], "status": row["status"], "has_summary": has_summary, "clean_char_count": clean_len}

        if (entry["raw_content"] or "").strip():
            clean_content = crud.clean_html(entry["raw_content"])
            if len(clean_content) >= min_chars:
                crud.save_fulltext(conn, entry_id, clean_content, "ok", "feed")
                clean_len = ai.estimate_clean_text_length(clean_content)
                return {"content": clean_content, "status": "ok", "has_summary": has_summary, "clean_char_count": clean_len}

    # 4. If feed refresh still didn't populate it (stale, video, paid, or dropped off feed), fall back to crawler
    import extractor
    content, status, fetcher = extractor.fetch_and_extract_fulltext(entry["url"])
    if status == "fetch_failed" and (entry["raw_content"] or "").strip():
        content = crud.clean_html(entry["raw_content"] or "")
        status = "ok"
        fetcher = "feed"
        
    with db.get_db() as conn:
        crud.save_fulltext(conn, entry_id, content, status, fetcher)
        
    clean_len = ai.estimate_clean_text_length(content or "")
    return {"content": content, "status": status, "has_summary": has_summary, "clean_char_count": clean_len}

def read_single_entry(entry_id: int) -> bool:
    with db.get_db() as conn:
        success = crud.mark_entry_read(conn, entry_id)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return True

def unread_single_entry(entry_id: int) -> bool:
    with db.get_db() as conn:
        success = crud.mark_entry_unread(conn, entry_id)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return True

def update_entry_attention(entry_id: int, attention: str) -> bool:
    if attention not in ["read", "skim", "glance"]:
        raise HTTPException(status_code=400, detail="Invalid attention level")
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        crud.update_entry_attention(conn, entry_id, attention)
        return True

def star_entry(entry_id: int) -> bool:
    with db.get_db() as conn:
        success = crud.update_entry_starred(conn, entry_id, True)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return True

def unstar_entry(entry_id: int) -> bool:
    with db.get_db() as conn:
        success = crud.update_entry_starred(conn, entry_id, False)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return True

def toggle_favorite(entry_id: int) -> Dict[str, int]:
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        new_starred = not bool(entry["is_starred"])
        success = crud.update_entry_starred(conn, entry_id, new_starred)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to toggle star status")
        return {"is_favorited": 1 if new_starred else 0}

def record_engagement(entry_id: int, active_dwell_ms: int, scrolled_pct: float, opened_original: bool) -> Dict[str, Any]:
    if active_dwell_ms < 2000:
        return {"ok": True, "skipped": True}
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        crud.record_engagement(conn, entry_id, active_dwell_ms, scrolled_pct, opened_original)
        return {"ok": True}
