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
    access_password: Optional[str] = None

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
        interest_profile_enabled=update.interest_profile_enabled,
        access_password=update.access_password
    )

class TestLLMRequest(BaseModel):
    ai_base_url: str
    ai_api_key: str
    ai_model: str

@router.post("/settings/test-llm")
def test_llm_connection(req: TestLLMRequest):
    import httpx
    import time
    
    url = f"{req.ai_base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if req.ai_api_key:
        headers["Authorization"] = f"Bearer {req.ai_api_key}"
        
    payload = {
        "model": req.ai_model,
        "messages": [
            {"role": "user", "content": "ping"}
        ],
        "max_tokens": 10
    }
    
    start_time = time.time()
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, headers=headers, json=payload)
        
        duration = time.time() - start_time
        
        if response.status_code != 200:
            return {
                "success": False,
                "message": f"API 返回状态码 {response.status_code}: {response.text}"
            }
            
        result = response.json()
        if "choices" not in result or len(result["choices"]) == 0:
            return {
                "success": False,
                "message": "API 返回的 choices 列表为空"
            }
            
        return {
            "success": True,
            "message": "连接成功！",
            "model_response": result["choices"][0]["message"]["content"]
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"请求接口失败: {str(e)}"
        }

@router.get("/settings/token-stats")
def get_token_stats():
    from db import get_db
    import crud
    with get_db() as conn:
        return crud.get_daily_token_stats(conn)
