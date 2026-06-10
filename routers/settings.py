import logging
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
import services.settings_service as settings_service

logger = logging.getLogger("myrss.routers.settings")
router = APIRouter()

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

@router.get("/settings")
def get_settings():
    return settings_service.get_settings()

@router.put("/settings")
def update_settings(update: SettingsUpdate):
    return settings_service.update_settings(
        fetch_interval_minutes=update.fetch_interval_minutes,
        min_text_chars=update.min_text_chars,
        promote_threshold=update.promote_threshold,
        ai_base_url=update.ai_base_url,
        ai_api_key=update.ai_api_key,
        ai_model=update.ai_model,
        ai_pregenerate=update.ai_pregenerate,
        ai_stream=update.ai_stream,
        ai_auto_summary=update.ai_auto_summary,
        ai_summary_length=update.ai_summary_length,
        ai_summary_lang=update.ai_summary_lang,
        system_lang=update.system_lang,
        chat_base_url=update.chat_base_url,
        chat_api_key=update.chat_api_key,
        chat_model=update.chat_model,
        chat_max_tokens=update.chat_max_tokens,
        interest_profile_enabled=update.interest_profile_enabled
    )
