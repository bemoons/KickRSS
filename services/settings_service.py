import logging
from typing import Optional, Dict, Any
from config import settings

logger = logging.getLogger("myrss.settings_service")

def get_settings() -> Dict[str, Any]:
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
        "chat_max_tokens": chat_cfg.get("max_tokens") or 1200,
        "chat_use_reasoning": chat_cfg.get("use_reasoning") if chat_cfg.get("use_reasoning") is not None else True,
        "access_password": settings.data.get("access_password", "")
    }

def update_settings(
    fetch_interval_minutes: Optional[int] = None,
    min_text_chars: Optional[int] = None,
    promote_threshold: Optional[int] = None,
    ai_base_url: Optional[str] = None,
    ai_api_key: Optional[str] = None,
    ai_model: Optional[str] = None,
    ai_pregenerate: Optional[bool] = None,
    ai_stream: Optional[bool] = None,
    ai_auto_summary: Optional[bool] = None,
    ai_summary_length: Optional[str] = None,
    ai_summary_lang: Optional[str] = None,
    system_lang: Optional[str] = None,
    chat_base_url: Optional[str] = None,
    chat_api_key: Optional[str] = None,
    chat_model: Optional[str] = None,
    chat_max_tokens: Optional[int] = None,
    chat_use_reasoning: Optional[bool] = None,
    interest_profile_enabled: Optional[bool] = None,
    access_password: Optional[str] = None
) -> Dict[str, Any]:
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
        
    if fetch_interval_minutes is not None:
        old_interval = settings.fetch_interval_minutes
        settings.data["fetch_interval_minutes"] = fetch_interval_minutes
        if fetch_interval_minutes != old_interval:
            from scheduler import reschedule_refresh_job
            reschedule_refresh_job(fetch_interval_minutes)
            
    if min_text_chars is not None:
        settings.data["fulltext"]["min_text_chars"] = min_text_chars
        
    if promote_threshold is not None:
        settings.data["classify"]["promote_threshold"] = promote_threshold
        
    if ai_base_url is not None:
        settings.data["ai"]["default"]["base_url"] = ai_base_url
        
    if ai_api_key is not None:
        settings.data["ai"]["default"]["api_key"] = ai_api_key
        
    if ai_model is not None:
        settings.data["ai"]["default"]["model"] = ai_model
        
    if ai_pregenerate is not None:
        settings.data["ai"]["pregenerate"] = ai_pregenerate
        
    if ai_stream is not None:
        settings.data["ai"]["stream"] = ai_stream

    if ai_auto_summary is not None:
        settings.data["ai"]["auto_summary"] = ai_auto_summary

    if ai_summary_length is not None:
        settings.data["ai"]["summary_length"] = ai_summary_length
        
    if ai_summary_lang is not None:
        settings.data["ai"]["summary_language"] = ai_summary_lang
        
    if system_lang is not None:
        settings.data["system_language"] = system_lang
        
    if chat_base_url is not None:
        settings.data["ai"]["tasks"]["chat"]["base_url"] = chat_base_url.strip() if chat_base_url.strip() else None
        
    if chat_api_key is not None:
        settings.data["ai"]["tasks"]["chat"]["api_key"] = chat_api_key.strip() if chat_api_key.strip() else None

    if chat_model is not None:
        settings.data["ai"]["tasks"]["chat"]["model"] = chat_model.strip() if chat_model.strip() else None
        
    if chat_max_tokens is not None:
        settings.data["ai"]["tasks"]["chat"]["max_tokens"] = chat_max_tokens
        
    if chat_use_reasoning is not None:
        settings.data["ai"]["tasks"]["chat"]["use_reasoning"] = chat_use_reasoning
        
    if interest_profile_enabled is not None:
        settings.data["interest_profile_enabled"] = interest_profile_enabled
        
    if access_password is not None:
        settings.data["access_password"] = access_password.strip()
        
    settings.save()
    return get_settings()
