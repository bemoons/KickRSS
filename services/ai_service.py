import logging
import json
import db
import crud
import ai
from typing import Optional, List, Dict, Any, Generator, Tuple
from fastapi import HTTPException
from config import settings

logger = logging.getLogger("myrss.ai_service")

def generate_stream_summary(entry_id: int, title: str, url: str, ft_text: str, dynamic_length: int, ai_model: str) -> Generator[str, None, None]:
    try:
        ai_stream = ai.generate_summary_stream(title, url, ft_text, length=dynamic_length, summary_lang=settings.summary_language)
        
        buffer = ""
        in_summary = False
        clickbait_note = None
        accumulated_summary = ""
        
        for chunk in ai_stream:
            # Skip empty chunks
            if not chunk:
                continue
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
                        # After extracting clickbait note, treat the rest as summary
                        in_summary = True
                        if rest.strip():
                            yield f"data: {json.dumps({'summary': rest.strip(), 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                            accumulated_summary += rest.strip()
                        buffer = ""
                    elif clickbait_note is not None:
                        # Already have clickbait note; treat content as summary
                        in_summary = True
                        if buffer.strip():
                            yield f"data: {json.dumps({'summary': buffer.strip(), 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                            accumulated_summary += buffer.strip()
                        buffer = ""
                    elif len(buffer) >= 10:
                        # No structured headers and enough content: treat as summary
                        in_summary = True
                        yield f"data: {json.dumps({'summary': buffer, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                        accumulated_summary += buffer
                        buffer = ""
                    else:
                        buffer = rest
                is_clickbait_prefix = "CLICKBAIT_NOTE:".startswith(buffer) or buffer.startswith("CLICKBAIT_NOTE:")
                if is_clickbait_prefix:
                    pass
                elif len(buffer) >= 30:
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
                crud.save_summary(conn, entry_id, final_summary, clickbait_note, ai_model)
                
        yield f"data: {json.dumps({'summary': '', 'clickbait_note': None, 'status': 'done'}, ensure_ascii=False)}\n\n"
        
    except Exception as e:
        logger.error(f"Error in stream summary service for entry {entry_id}: {e}", exc_info=True)
        yield f"data: {json.dumps({'summary': '', 'clickbait_note': None, 'status': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"

def get_entry_summary(entry_id: int, stream: Optional[bool] = None, force: Optional[bool] = None, cache_only: bool = False) -> Tuple[bool, Any]:
    """
    Get summary for an entry.
    Returns:
        (is_stream, result_or_generator)
    """
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
            
            ai_cfg = settings.get_ai_config("summary")
            do_stream = stream if stream is not None else ai_cfg.get("stream", True)
            
            if do_stream:
                def stream_cached():
                    if cached_click:
                        yield f"data: {json.dumps({'summary': '', 'clickbait_note': cached_click, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'summary': cached_sum, 'clickbait_note': None, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'summary': '', 'clickbait_note': None, 'status': 'done'}, ensure_ascii=False)}\n\n"
                return True, stream_cached()
            else:
                return False, {
                    "summary": cached_sum,
                    "clickbait_note": cached_click,
                    "status": "ok"
                }

        if cache_only:
            return False, {
                "summary": "",
                "clickbait_note": None,
                "status": "no_cache"
            }

    # Ensure fulltext exists
    with db.get_db() as conn:
        ft_row = crud.get_entry_fulltext(conn, entry_id)
        
    if not ft_row:
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
            return True, stream_no_text()
        else:
            return False, {
                "summary": no_text_msg,
                "clickbait_note": None,
                "status": "no_text"
            }

    # Estimate clean text length and decide dynamic summary length
    clean_char_count = ai.estimate_clean_text_length(ft_text)
    target_chars = min(max(int(clean_char_count * 0.1), 100), 900)
    dynamic_length = target_chars

    ai_cfg = settings.get_ai_config("summary", summary_length=str(dynamic_length))
    do_stream = stream if stream is not None else ai_cfg.get("stream", True)

    if do_stream:
        generator = generate_stream_summary(
            entry_id, entry["title"], entry["url"], ft_text, dynamic_length, ai_cfg["model"]
        )
        return True, generator
    else:
        try:
            raw_response = ai.generate_summary_sync(entry["title"], entry["url"], ft_text, length=dynamic_length, summary_lang=settings.summary_language)
            summary_text, clickbait = ai.parse_ai_summary_response(raw_response)
            
            with db.get_db() as conn:
                crud.save_summary(conn, entry_id, summary_text, clickbait, ai_cfg["model"])
                
            return False, {
                "summary": summary_text,
                "clickbait_note": clickbait,
                "status": "ok"
            }
        except Exception as e:
            logger.error(f"Error generating sync summary: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

def get_entry_translation(entry_id: int, force: Optional[bool] = None) -> Dict[str, Any]:
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        target_lang = settings.summary_language
        if target_lang == "auto":
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
        
    source_lang = ai.detect_language(ft_content)
    is_source_zh = (source_lang in ["zh", "zh-hant"])
    is_target_zh = (target_lang in ["zh", "zh-hant"])
    
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

def translate_entry_paragraph(entry_id: int, para_index: int, text: str) -> Dict[str, Any]:
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        target_lang = settings.summary_language
        if target_lang == "auto":
            target_lang = settings.system_language
            
        text_to_translate = text.strip()
        if not text_to_translate:
            return {"translated_text": "", "status": "ok"}
            
        cached = crud.get_paragraph_translation(conn, entry_id, para_index, target_lang)
        if cached and cached["original_text"] == text_to_translate:
            return {
                "translated_text": cached["translated_text"],
                "status": "ok"
            }
            
    source_lang = ai.detect_language(text_to_translate)
    is_source_zh = (source_lang in ["zh", "zh-hant"])
    is_target_zh = (target_lang in ["zh", "zh-hant"])
    
    if source_lang == target_lang or (is_source_zh and is_target_zh):
        translated_text = text_to_translate
    else:
        try:
            translated_text = ai.generate_translation(entry["title"], text_to_translate, target_lang)
        except Exception as e:
            logger.error(f"Failed to translate paragraph {para_index}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
            
    with db.get_db() as conn:
        crud.save_paragraph_translation(conn, entry_id, para_index, target_lang, text_to_translate, translated_text)
        
    return {
        "translated_text": translated_text,
        "status": "ok"
    }

def generate_stream_chat(entry_id: int, title: str, fulltext: Optional[str], summary: Optional[str], chat_history: List[Dict[str, str]], new_message: str) -> Generator[str, None, None]:
    try:
        ai_stream = ai.generate_chat_response_stream(
            title, fulltext, summary, chat_history, new_message
        )
        accumulated_reply = ""
        for chunk, is_reasoning in ai_stream:
            if is_reasoning:
                yield f"data: {json.dumps({'reply': chunk, 'status': 'thinking'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'reply': chunk, 'status': 'streaming'}, ensure_ascii=False)}\n\n"
                accumulated_reply += chunk
            
        final_reply = accumulated_reply.strip()
        if final_reply:
            with db.get_db() as conn:
                crud.save_chat_message(conn, entry_id, "assistant", final_reply)
                
        yield f"data: {json.dumps({'reply': '', 'status': 'done'}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"Error streaming chat response for entry {entry_id}: {e}", exc_info=True)
        yield f"data: {json.dumps({'reply': '', 'status': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"

def chat_with_entry(entry_id: int, message: str, stream: Optional[bool] = None) -> Tuple[bool, Any]:
    """
    Chat with entry context.
    Returns:
        (is_stream, result_or_generator)
    """
    ai_cfg = settings.get_ai_config("chat")
    do_stream = stream if stream is not None else ai_cfg.get("stream", True)
    
    with db.get_db() as conn:
        entry = crud.get_entry_by_id(conn, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
            
        ft_row = crud.get_entry_fulltext(conn, entry_id)
        summary_row = crud.get_entry_summary(conn, entry_id)
        
        fulltext = ft_row["content"] if ft_row else entry["raw_content"]
        summary = summary_row["content"] if summary_row else None
        
        history_rows = crud.get_chat_history(conn, entry_id)
        chat_history = [{"role": h["role"], "content": h["content"]} for h in history_rows]
        
        crud.save_chat_message(conn, entry_id, "user", message)
        
    if do_stream:
        generator = generate_stream_chat(entry_id, entry["title"], fulltext, summary, chat_history, message)
        return True, generator
    else:
        try:
            reply = ai.generate_chat_response_sync(
                entry["title"], fulltext, summary, chat_history, message
            )
            with db.get_db() as conn:
                crud.save_chat_message(conn, entry_id, "assistant", reply.strip())
                updated_history = crud.get_chat_history(conn, entry_id)
                history_list = [{"role": h["role"], "content": h["content"]} for h in updated_history]
                
            return False, {
                "reply": reply.strip(),
                "history": history_list
            }
        except Exception as e:
            logger.error(f"Error in sync chat response: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
