import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
import crud
import opml
import ai
from config import settings
from ingester import FeedparserIngester
from classifier import classify_feed_entries
from scheduler import start_scheduler, shutdown_scheduler, refresh_all_feeds, refresh_single_feed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("myrss")

# Background task for seeding a newly added feed
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
        
        with db.get_db() as conn:
            # Save generated categories
            if seed_categories:
                crud.save_categories(conn, feed_id, seed_categories)
                
            # Update feed title and site url from parsed feed if available
            title = result.feed_title or feed["title"]
            site_url = result.site_url or feed["site_url"]
            
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE feeds SET title = ?, site_url = ?, seeded = 1 WHERE id = ?",
                (title, site_url, feed_id)
            )
            
            default_cat_id = crud.get_default_category(conn, feed_id)
            new_count = crud.save_entries(conn, feed_id, result.entries, default_cat_id)
            crud.update_feed_fetch_status(conn, feed_id, result.etag, result.last_modified)
            
            logger.info(f"Cold start entries stored for feed {feed_id}: {new_count} entries saved.")
            
        # 2. Run batch classification on the newly saved entries
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
            # 1. Delete all custom categories (where is_default = 0)
            cursor.execute("DELETE FROM categories WHERE feed_id = ? AND is_default = 0", (feed_id,))
            # 2. Update all entries of this feed to default category and clear classified_at
            cursor.execute("UPDATE entries SET category_id = ?, classified_at = NULL WHERE feed_id = ?", (default_cat_id, feed_id))
            # 3. Retrieve up to 100 recent entries to seed
            titles = []
            if need_classify:
                cursor.execute("SELECT title FROM entries WHERE feed_id = ? ORDER BY published_at DESC LIMIT 100", (feed_id,))
                titles = [r["title"] for r in cursor.fetchall() if r["title"]]
            conn.commit()
            
        # 4. Generate new seed categories using AI
        seed_categories = []
        if titles and need_classify:
            try:
                seed_categories = ai.generate_seed_categories(titles)
                logger.info(f"AI generated categories for reset of feed {feed_id}: {seed_categories}")
            except Exception as ae:
                logger.error(f"AI category generation failed during reset of feed {feed_id}: {ae}")
                
        with db.get_db() as conn:
            if seed_categories and need_classify:
                crud.save_categories(conn, feed_id, seed_categories)
                
            cursor = conn.cursor()
            cursor.execute("UPDATE feeds SET seeded = 1 WHERE id = ?", (feed_id,))
            conn.commit()
            
    except Exception as e:
        logger.error(f"Failed to clear and seed categories for feed {feed_id}: {e}", exc_info=True)
        raise e

def async_reset_feed_categories(feed_id: int):
    logger.info(f"Starting async category reset for feed {feed_id}")
    try:
        from classifier import classify_feed_entries
        sync_reset_feed_categories_step1(feed_id)
        classify_feed_entries(feed_id)
        logger.info(f"Finished category reset and classification for feed {feed_id}")
    except Exception as e:
        logger.error(f"Failed to reset categories for feed {feed_id}: {e}", exc_info=True)

# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema
    db.init_db()
    
    # Start the background scheduler
    start_scheduler()
    
    yield
    
    # Shutdown the background scheduler
    shutdown_scheduler()

app = FastAPI(
    title="KickRSS API Backend",
    description="Backend for AI RSS Reader (Phase 1)",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic schemas
class FeedCreate(BaseModel):
    url: str

class FeedUpdate(BaseModel):
    title: Optional[str] = None
    enabled: Optional[bool] = None
    need_classification: Optional[bool] = None

class ReadEntries(BaseModel):
    ids: List[int]

class ChatRequest(BaseModel):
    message: str

class AttentionRequest(BaseModel):
    attention: str

class TranslateParagraphRequest(BaseModel):
    para_index: int
    text: str

class SettingsUpdate(BaseModel):
    fetch_interval_minutes: Optional[int] = None
    min_text_chars: Optional[int] = None
    promote_threshold: Optional[int] = None
    ai_base_url: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None
    ai_pregenerate: Optional[bool] = None
    ai_stream: Optional[bool] = None
    ai_auto_summary: Optional[bool] = None
    ai_summary_length: Optional[str] = None
    chat_base_url: Optional[str] = None
    chat_api_key: Optional[str] = None
    chat_model: Optional[str] = None
    chat_max_tokens: Optional[int] = None
    ai_summary_lang: Optional[str] = None
    system_lang: Optional[str] = None
    interest_profile_enabled: Optional[bool] = None

class EngagementRequest(BaseModel):
    active_dwell_ms: int
    scrolled_pct: float
    opened_original: bool

# Endpoints

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/feeds")
def get_feeds():
    with db.get_db() as conn:
        rows = crud.list_feeds(conn)
        return [dict(r) for r in rows]

@app.post("/feeds")
def add_feed(feed_in: FeedCreate, background_tasks: BackgroundTasks):
    url = feed_in.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid feed URL scheme (must be http or https)")
        
    with db.get_db() as conn:
        # Check if already exists
        existing = crud.get_feed_by_url(conn, url)
        if existing:
            return dict(existing)
            
        # Add to database with temporary title
        feed_id = crud.add_feed(conn, url, title=url)
        feed_row = crud.get_feed_by_id(conn, feed_id)
        feed_dict = dict(feed_row) if feed_row else {}
        
    # Trigger asynchronous cold start seeding
    background_tasks.add_task(async_cold_start_feed, feed_id)
    return feed_dict

@app.put("/feeds/{feed_id}")
def update_feed(feed_id: int, feed_in: FeedUpdate):
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
        if feed_in.title is not None:
            crud.update_feed_title(conn, feed_id, feed_in.title.strip())
        if feed_in.enabled is not None:
            crud.update_feed_enabled(conn, feed_id, feed_in.enabled)
        if feed_in.need_classification is not None:
            crud.update_feed_need_classification(conn, feed_id, feed_in.need_classification)
        updated = crud.get_feed_by_id(conn, feed_id)
        return dict(updated)

@app.delete("/feeds/{feed_id}")
def delete_feed(feed_id: int):
    with db.get_db() as conn:
        success = crud.delete_feed(conn, feed_id)
        if not success:
            raise HTTPException(status_code=404, detail="Feed not found")
        return {"ok": True}

@app.get("/feeds/{feed_id}/categories")
def get_feed_categories(feed_id: int):
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
        rows = crud.get_categories_for_feed(conn, feed_id)
        return [dict(r) for r in rows]

@app.get("/categories/{category_id}/entries")
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

@app.get("/feeds/{feed_id}/entries")
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

@app.get("/search")
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

@app.get("/entries/{entry_id}/fulltext")
def get_entry_fulltext(entry_id: int):
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        
        has_summary = False
        summary_row = crud.get_entry_summary(conn, entry_id)
        if summary_row and summary_row["content"] and summary_row["content"].strip():
            has_summary = True
        
        row = crud.get_entry_fulltext(conn, entry_id)
        if row:
            clean_len = ai.estimate_clean_text_length(row["content"] or "")
            return {"content": row["content"], "status": row["status"], "has_summary": has_summary, "clean_char_count": clean_len}
            
    # Do not try to load the web page (WAF). Rely on RSS raw content.
    content = crud.clean_html(entry["raw_content"] or "")
    status = "ok"
    fetcher = "feed"
    
    with db.get_db() as conn:
        crud.save_fulltext(conn, entry_id, content, status, fetcher)
        
    clean_len = ai.estimate_clean_text_length(content or "")
    return {"content": content, "status": status, "has_summary": has_summary, "clean_char_count": clean_len}

@app.post("/entries/{entry_id}/read")
def read_single_entry(entry_id: int):
    with db.get_db() as conn:
        success = crud.mark_entry_read(conn, entry_id)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"ok": True}

@app.post("/entries/{entry_id}/unread")
def unread_single_entry(entry_id: int):
    with db.get_db() as conn:
        success = crud.mark_entry_unread(conn, entry_id)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"ok": True}

@app.post("/entries/{entry_id}/attention")
def update_entry_attention(entry_id: int, req: AttentionRequest):
    if req.attention not in ["read", "skim", "glance"]:
        raise HTTPException(status_code=400, detail="Invalid attention level")
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        crud.update_entry_attention(conn, entry_id, req.attention)
        return {"ok": True}

@app.get("/entries/unread")
def get_unread_entries_api(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    with db.get_db() as conn:
        rows = crud.get_unread_entries(conn, limit=limit, offset=offset)
        return [dict(r) for r in rows]

@app.get("/entries/starred")
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

@app.get("/entries/starred/count")
def get_starred_count():
    with db.get_db() as conn:
        return crud.get_starred_entries_count(conn)

@app.post("/entries/{entry_id}/star")
def star_entry(entry_id: int):
    with db.get_db() as conn:
        success = crud.update_entry_starred(conn, entry_id, True)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"ok": True}

@app.post("/entries/{entry_id}/unstar")
def unstar_entry(entry_id: int):
    with db.get_db() as conn:
        success = crud.update_entry_starred(conn, entry_id, False)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"ok": True}

@app.post("/entries/read")
def read_multiple_entries(req: ReadEntries):
    with db.get_db() as conn:
        count = crud.mark_entries_read(conn, req.ids)
        return {"ok": True, "count": count, "ids": req.ids}

@app.post("/categories/{category_id}/read")
def read_category(category_id: int):
    with db.get_db() as conn:
        ids = crud.mark_category_read(conn, category_id)
        return {"ok": True, "count": len(ids), "ids": ids}

@app.post("/feeds/{feed_id}/read")
def read_feed(feed_id: int):
    with db.get_db() as conn:
        ids = crud.mark_feed_read(conn, feed_id)
        return {"ok": True, "count": len(ids), "ids": ids}

@app.post("/entries/unread")
def unread_multiple_entries(req: ReadEntries):
    with db.get_db() as conn:
        count = crud.mark_entries_unread(conn, req.ids)
        return {"ok": True, "count": count}

@app.post("/import/opml")
async def import_opml(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
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
    return {"ok": True, "added": added_count}

@app.get("/export/opml")
def export_opml():
    from fastapi.responses import Response
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

@app.get("/settings")
def get_settings():
    ai_cfg = settings.data.get("ai", {})
    default_ai = ai_cfg.get("default", {})
    chat_cfg = ai_cfg.get("tasks", {}).get("chat", {})
    fulltext_cfg = settings.data.get("fulltext", {})
    classify_cfg = settings.data.get("classify", {})
    
    return {
        "fetch_interval_minutes": settings.fetch_interval_minutes,
        "min_text_chars": settings.min_text_chars,
        "promote_threshold": settings.promote_threshold,
        
        "ai_base_url": default_ai.get("base_url", "http://localhost:9999/v1"),
        "ai_api_key": default_ai.get("api_key", ""),
        "ai_model": default_ai.get("model", "qwen-local"),
        
        "ai_pregenerate": ai_cfg.get("pregenerate", False),
        "ai_stream": ai_cfg.get("stream", True),
        "ai_auto_summary": ai_cfg.get("auto_summary", True),
        "ai_summary_length": ai_cfg.get("summary_length", "medium"),
        "ai_summary_lang": ai_cfg.get("summary_language", "auto"),
        "system_lang": settings.data.get("system_language", "zh"),
        "interest_profile_enabled": settings.data.get("interest_profile_enabled", False),
        
        "chat_base_url": chat_cfg.get("base_url") or "",
        "chat_api_key": chat_cfg.get("api_key") or "",
        "chat_model": chat_cfg.get("model") or "",
        "chat_max_tokens": chat_cfg.get("max_tokens") or 1200
    }

@app.put("/settings")
def update_settings(update: SettingsUpdate):
    if "ai" not in settings.data:
        settings.data["ai"] = {}
    if "default" not in settings.data["ai"]:
        settings.data["ai"]["default"] = {}
    if "tasks" not in settings.data["ai"]:
        settings.data["ai"]["tasks"] = {}
    if "chat" not in settings.data["ai"]["tasks"]:
        settings.data["ai"]["tasks"]["chat"] = {}
    if "fulltext" not in settings.data:
        settings.data["fulltext"] = {}
    if "classify" not in settings.data:
        settings.data["classify"] = {}
        
    if update.fetch_interval_minutes is not None:
        old_interval = settings.fetch_interval_minutes
        settings.data["fetch_interval_minutes"] = update.fetch_interval_minutes
        if update.fetch_interval_minutes != old_interval:
            from scheduler import reschedule_refresh_job
            reschedule_refresh_job(update.fetch_interval_minutes)
            
    if update.min_text_chars is not None:
        settings.data["fulltext"]["min_text_chars"] = update.min_text_chars
        
    if update.promote_threshold is not None:
        settings.data["classify"]["promote_threshold"] = update.promote_threshold
        
    if update.ai_base_url is not None:
        settings.data["ai"]["default"]["base_url"] = update.ai_base_url
        
    if update.ai_api_key is not None:
        settings.data["ai"]["default"]["api_key"] = update.ai_api_key
        
    if update.ai_model is not None:
        settings.data["ai"]["default"]["model"] = update.ai_model
        
    if update.ai_pregenerate is not None:
        settings.data["ai"]["pregenerate"] = update.ai_pregenerate
        
    if update.ai_stream is not None:
        settings.data["ai"]["stream"] = update.ai_stream

    if update.ai_auto_summary is not None:
        settings.data["ai"]["auto_summary"] = update.ai_auto_summary

    if update.ai_summary_length is not None:
        settings.data["ai"]["summary_length"] = update.ai_summary_length
        
    if update.ai_summary_lang is not None:
        settings.data["ai"]["summary_language"] = update.ai_summary_lang
        
    if update.system_lang is not None:
        settings.data["system_language"] = update.system_lang
        
    if update.chat_base_url is not None:
        settings.data["ai"]["tasks"]["chat"]["base_url"] = update.chat_base_url.strip() if update.chat_base_url.strip() else None
        
    if update.chat_api_key is not None:
        settings.data["ai"]["tasks"]["chat"]["api_key"] = update.chat_api_key.strip() if update.chat_api_key.strip() else None

    if update.chat_model is not None:
        settings.data["ai"]["tasks"]["chat"]["model"] = update.chat_model.strip() if update.chat_model.strip() else None
        
    if update.chat_max_tokens is not None:
        settings.data["ai"]["tasks"]["chat"]["max_tokens"] = update.chat_max_tokens
        
    if update.interest_profile_enabled is not None:
        settings.data["interest_profile_enabled"] = update.interest_profile_enabled
        
    settings.save()
    return get_settings()

@app.post("/refresh")
def force_refresh_all():
    processed, total_new = refresh_all_feeds()
    return {"ok": True, "fetched": processed, "new_entries": total_new}

@app.get("/entries/{entry_id}/summary")
def get_entry_summary(entry_id: int, stream: Optional[bool] = None, force: Optional[bool] = None):
    from fastapi.responses import StreamingResponse
    import json
    
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        if force:
            crud.delete_summary(conn, entry_id)
            summary_row = None
        else:
            summary_row = crud.get_entry_summary(conn, entry_id)
        
        if summary_row:
            cached_sum = summary_row["content"]
            cached_click = summary_row["clickbait_note"]
            
            # Retrieve default config to check stream settings
            ai_cfg = settings.get_ai_config("summary")
            do_stream = stream if stream is not None else ai_cfg.get("stream", True)
            
            if do_stream:
                def stream_cached():
                    if cached_click:
                        yield f"data: {json.dumps({'summary': '', 'clickbait_note': cached_click, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'summary': cached_sum, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'summary': '', 'clickbait_note': None, 'status': 'done'}, ensure_ascii=False)}\n\n"
                return StreamingResponse(stream_cached(), media_type="text/event-stream")
            else:
                return {
                    "summary": cached_sum,
                    "clickbait_note": cached_click,
                    "status": "ok"
                }

    # Ensure fulltext exists
    with db.get_db() as conn:
        ft_row = crud.get_entry_fulltext(conn, entry_id)
        
    if not ft_row:
        # Do not try to load the web page (WAF). Rely on RSS raw content.
        ft_content = crud.clean_html(entry["raw_content"] or "")
        ft_status = "ok"
        ft_fetcher = "feed"
        with db.get_db() as conn:
            crud.save_fulltext(conn, entry_id, ft_content, ft_status, ft_fetcher)
        ft_text = ft_content
        ft_stat = ft_status
    else:
        ft_text = ft_row["content"]
        ft_stat = ft_row["status"]

    # Check for empty content
    if ft_stat != "ok" or not ft_text or len(ft_text) < settings.min_text_chars:
        no_text_msg = "此文主要为视频/图片，无正文可总结。"
        with db.get_db() as conn:
            crud.save_summary(conn, entry_id, no_text_msg, None, "system")
            
        ai_cfg = settings.get_ai_config("summary")
        do_stream = stream if stream is not None else ai_cfg.get("stream", True)
        if do_stream:
            def stream_no_text():
                yield f"data: {json.dumps({'summary': no_text_msg, 'clickbait_note': None, 'status': 'no_text'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(stream_no_text(), media_type="text/event-stream")
        else:
            return {
                "summary": no_text_msg,
                "clickbait_note": None,
                "status": "no_text"
            }

    # Estimate clean text length and decide dynamic summary length (1/10 of clean text, max 900)
    clean_char_count = ai.estimate_clean_text_length(ft_text)
    target_chars = min(max(int(clean_char_count * 0.1), 100), 900)
    dynamic_length = target_chars

    ai_cfg = settings.get_ai_config("summary", summary_length=str(dynamic_length))
    do_stream = stream if stream is not None else ai_cfg.get("stream", True)

    # AI summarization
    if do_stream:
        def stream_summary_generator():
            try:
                ai_stream = ai.generate_summary_stream(entry["title"], entry["url"], ft_text, length=dynamic_length, summary_lang=settings.summary_language)
                
                buffer = ""
                in_summary = False
                clickbait_note = None
                accumulated_summary = ""
                
                for chunk in ai_stream:
                    buffer += chunk
                    
                    if not in_summary:
                        if "SUMMARY:" in buffer:
                            parts = buffer.split("SUMMARY:", 1)
                            before_sum = parts[0].strip()
                            after_sum = parts[1].lstrip()
                            
                            if before_sum.startswith("CLICKBAIT_NOTE:"):
                                note_val = before_sum.replace("CLICKBAIT_NOTE:", "").strip()
                                if note_val.upper() != "NONE" and note_val:
                                    clickbait_note = note_val
                                    yield f"data: {json.dumps({'summary': '', 'clickbait_note': clickbait_note, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                            
                            in_summary = True
                            if after_sum:
                                yield f"data: {json.dumps({'summary': after_sum, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                                accumulated_summary += after_sum
                            buffer = ""
                        elif "\n" in buffer:
                            parts = buffer.split("\n", 1)
                            first_line = parts[0].strip()
                            rest = parts[1]
                            
                            if first_line.startswith("CLICKBAIT_NOTE:"):
                                note_val = first_line.replace("CLICKBAIT_NOTE:", "").strip()
                                if note_val.upper() != "NONE" and note_val:
                                    clickbait_note = note_val
                                    yield f"data: {json.dumps({'summary': '', 'clickbait_note': clickbait_note, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                            buffer = rest
                        elif len(buffer) >= 250:
                            in_summary = True
                            yield f"data: {json.dumps({'summary': buffer, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                            accumulated_summary += buffer
                            buffer = ""
                    else:
                        yield f"data: {json.dumps({'summary': buffer, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                        accumulated_summary += buffer
                        buffer = ""
                        
                # Process remaining buffer
                if buffer:
                    if not in_summary:
                        sum_text, click = ai.parse_ai_summary_response(buffer)
                        if click:
                            yield f"data: {json.dumps({'summary': '', 'clickbait_note': click, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                            clickbait_note = click
                        yield f"data: {json.dumps({'summary': sum_text, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                        accumulated_summary += sum_text
                    else:
                        yield f"data: {json.dumps({'summary': buffer, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                        accumulated_summary += buffer
                        
                final_summary = accumulated_summary.strip()
                if final_summary:
                    with db.get_db() as conn:
                        crud.save_summary(conn, entry_id, final_summary, clickbait_note, ai_cfg["model"])
                        
                yield f"data: {json.dumps({'summary': '', 'clickbait_note': None, 'status': 'done'}, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                logger.error(f"Error in stream summary: {e}", exc_info=True)
                yield f"data: {json.dumps({'summary': '', 'clickbait_note': None, 'status': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"
                
        return StreamingResponse(stream_summary_generator(), media_type="text/event-stream")
        
    else:
        try:
            raw_response = ai.generate_summary_sync(entry["title"], entry["url"], ft_text, length=dynamic_length, summary_lang=settings.summary_language)
            summary_text, clickbait = ai.parse_ai_summary_response(raw_response)
            
            with db.get_db() as conn:
                crud.save_summary(conn, entry_id, summary_text, clickbait, ai_cfg["model"])
                
            return {
                "summary": summary_text,
                "clickbait_note": clickbait,
                "status": "ok"
            }
        except Exception as e:
            logger.error(f"Error generating sync summary: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/entries/{entry_id}/translate")
def get_entry_translation(entry_id: int, force: Optional[bool] = None):
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        target_lang = settings.summary_language
        if target_lang == "auto":
            # Fallback to the system language if auto mode is selected since translation needs a specific language
            target_lang = settings.system_language
            
        if force:
            crud.delete_translation(conn, entry_id)
            crud.delete_paragraph_translations(conn, entry_id)
            trans_row = None
        else:
            trans_row = crud.get_entry_translation(conn, entry_id)
            
        if trans_row and trans_row["lang"] == target_lang:
            return {
                "translated_content": trans_row["content"],
                "target_lang": trans_row["lang"],
                "status": "ok"
            }
            
    # Load fulltext to translate
    with db.get_db() as conn:
        ft_row = crud.get_entry_fulltext(conn, entry_id)
        
    if not ft_row:
        ft_content = crud.clean_html(entry["raw_content"] or "")
    else:
        ft_content = ft_row["content"]
        
    if not ft_content or len(ft_content.strip()) < 5:
        raise HTTPException(status_code=400, detail="No content to translate.")
        
    # Detect the language of the source text
    source_lang = ai.detect_language(ft_content)
    
    is_source_zh = (source_lang in ["zh", "zh-hant"])
    is_target_zh = (target_lang in ["zh", "zh-hant"])
    
    # Bypass translation if source and target languages are identical (or both Chinese)
    if source_lang == target_lang or (is_source_zh and is_target_zh):
        with db.get_db() as conn:
            crud.save_translation(conn, entry_id, ft_content, target_lang)
        return {
            "translated_content": ft_content,
            "target_lang": target_lang,
            "status": "ok"
        }
        
    try:
        translated_text = ai.generate_translation(entry["title"], ft_content, target_lang)
        
        with db.get_db() as conn:
            crud.save_translation(conn, entry_id, translated_text, target_lang)
            
        return {
            "translated_content": translated_text,
            "target_lang": target_lang,
            "status": "ok"
        }
    except Exception as e:
        logger.error(f"Failed to generate translation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entries/{entry_id}/translate_paragraph")
def translate_entry_paragraph(entry_id: int, req: TranslateParagraphRequest):
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        target_lang = settings.summary_language
        if target_lang == "auto":
            target_lang = settings.system_language
            
        # Clean text
        text_to_translate = req.text.strip()
        if not text_to_translate:
            return {"translated_text": "", "status": "ok"}
            
        # 1. Check if cached paragraph translation exists
        cached = crud.get_paragraph_translation(conn, entry_id, req.para_index, target_lang)
        if cached and cached["original_text"] == text_to_translate:
            return {
                "translated_text": cached["translated_text"],
                "status": "ok"
            }
            
    # 2. Check if we need to call AI (e.g. if languages match, bypass translation)
    source_lang = ai.detect_language(text_to_translate)
    is_source_zh = (source_lang in ["zh", "zh-hant"])
    is_target_zh = (target_lang in ["zh", "zh-hant"])
    
    if source_lang == target_lang or (is_source_zh and is_target_zh):
        translated_text = text_to_translate
    else:
        try:
            # We call translate on just this single paragraph text
            translated_text = ai.generate_translation(entry["title"], text_to_translate, target_lang)
        except Exception as e:
            logger.error(f"Failed to translate paragraph {req.para_index}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
            
    # Save cache
    with db.get_db() as conn:
        crud.save_paragraph_translation(conn, entry_id, req.para_index, target_lang, text_to_translate, translated_text)
        
    return {
        "translated_text": translated_text,
        "status": "ok"
    }

@app.post("/entries/{entry_id}/chat")
def chat_with_entry(entry_id: int, req: ChatRequest, stream: Optional[bool] = None):
    from fastapi.responses import StreamingResponse
    import json
    
    ai_cfg = settings.get_ai_config("chat")
    do_stream = stream if stream is not None else ai_cfg.get("stream", True)
    
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        # Get context metadata: fulltext and summary
        ft_row = crud.get_entry_fulltext(conn, entry_id)
        summary_row = crud.get_entry_summary(conn, entry_id)
        
        fulltext = ft_row["content"] if ft_row else entry["raw_content"]
        summary = summary_row["content"] if summary_row else None
        
        # 1. Fetch previous history (excluding the new message)
        history_rows = crud.get_chat_history(conn, entry_id)
        chat_history = [{"role": h["role"], "content": h["content"]} for h in history_rows]
        
        # 2. Save user message to database
        crud.save_chat_message(conn, entry_id, "user", req.message)
        
    new_message = req.message
    
    if do_stream:
        def stream_chat_generator():
            try:
                ai_stream = ai.generate_chat_response_stream(
                    entry["title"], fulltext, summary, chat_history, new_message
                )
                accumulated_reply = ""
                for chunk, is_reasoning in ai_stream:
                    if is_reasoning:
                        yield f"data: {json.dumps({'reply': chunk, 'status': 'thinking'}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'reply': chunk, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                        accumulated_reply += chunk
                    
                # Save assistant response to DB
                final_reply = accumulated_reply.strip()
                if final_reply:
                    with db.get_db() as conn:
                        crud.save_chat_message(conn, entry_id, "assistant", final_reply)
                        
                yield f"data: {json.dumps({'reply': '', 'status': 'done'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"Error streaming chat response: {e}", exc_info=True)
                yield f"data: {json.dumps({'reply': '', 'status': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"
                
        return StreamingResponse(stream_chat_generator(), media_type="text/event-stream")
        
    else:
        # Non-streaming chat response
        try:
            reply = ai.generate_chat_response_sync(
                entry["title"], fulltext, summary, chat_history, new_message
            )
            with db.get_db() as conn:
                crud.save_chat_message(conn, entry_id, "assistant", reply.strip())
                # Get updated full history
                updated_history = crud.get_chat_history(conn, entry_id)
                history_list = [{"role": h["role"], "content": h["content"]} for h in updated_history]
                
            return {
                "reply": reply.strip(),
                "history": history_list
            }
        except Exception as e:
            logger.error(f"Error in sync chat response: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/maintenance")
def trigger_maintenance():
    from maintenance import run_all_feeds_maintenance
    report = run_all_feeds_maintenance()
    return {"ok": True, "result": report}

@app.post("/feeds/reset-categories")
def reset_all_feeds_categories(background_tasks: BackgroundTasks):
    with db.get_db() as conn:
        feeds = crud.list_feeds(conn)
        
    for feed in feeds:
        if feed["enabled"]:
            background_tasks.add_task(async_reset_feed_categories, feed["id"])
            
    return {"ok": True, "message": f"Triggered category reset for {len(feeds)} feeds."}

@app.post("/feeds/{feed_id}/reset-categories")
def reset_single_feed_categories(feed_id: int, background_tasks: BackgroundTasks):
    with db.get_db() as conn:
        feed = crud.get_feed_by_id(conn, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
            
    sync_reset_feed_categories_step1(feed_id)
    
    from classifier import classify_feed_entries
    background_tasks.add_task(classify_feed_entries, feed_id)
    return {"ok": True, "message": f"Category reset and seeding completed for feed {feed_id}. Classification enqueued in background."}

@app.get("/entries/{entry_id}/chat")
def get_entry_chat_history(entry_id: int):
    with db.get_db() as conn:
        rows = crud.get_chat_history(conn, entry_id)
        return [dict(r) for r in rows]

@app.delete("/chat-messages/{message_id}")
def delete_chat_message(message_id: int):
    with db.get_db() as conn:
        success = crud.delete_chat_message(conn, message_id)
        if not success:
            raise HTTPException(status_code=404, detail="Message not found")
        return {"ok": True}

# ----------------------------------------------------
# ATTENTION PERSONALIZATION & USER PROFILE ENDPOINTS
# ----------------------------------------------------

@app.post("/entries/{entry_id}/engagement")
def record_engagement(entry_id: int, req: EngagementRequest):
    if req.active_dwell_ms < 2000:
        return {"ok": True, "skipped": True}
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        crud.record_engagement(conn, entry_id, req.active_dwell_ms, req.scrolled_pct, req.opened_original)
        return {"ok": True}

@app.post("/entries/{entry_id}/favorite")
def toggle_favorite(entry_id: int):
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        new_starred = not bool(entry["is_starred"])
        success = crud.update_entry_starred(conn, entry_id, new_starred)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to toggle star status")
        return {"is_favorited": 1 if new_starred else 0}

@app.get("/profile/interests")
def get_interest_profile():
    if not settings.interest_profile_enabled:
        return {"status": "disabled"}
        
    with db.get_db() as conn:
        latest = crud.get_latest_user_interest(conn)
        if not latest:
            return {
                "status": "cold_start",
                "message": "阅读数据积累中，需至少15篇文章的阅读行为"
            }
            
        import json
        try:
            topics = json.loads(latest["topics_json"])
        except Exception:
            topics = {"high_interest": [], "low_interest": [], "concentration_note": None}
            
        return {
            "snapshot_date": latest["snapshot_date"],
            "total_articles": latest["total_articles"],
            "high_engagement": latest["high_engagement"],
            "low_engagement": latest["low_engagement"],
            "topics": topics,
            "attention_guide": latest["prompt_text"]
        }

@app.get("/profile/topic-detail")
def get_topic_detail(topic: str):
    if not settings.interest_profile_enabled:
        raise HTTPException(status_code=400, detail="Personalization profile is disabled")
        
    with db.get_db() as conn:
        detail = crud.get_topic_detail(conn, topic)
        if not detail:
            raise HTTPException(status_code=404, detail="Topic not found or no data available")
        return detail

# Serve frontend static files
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)

