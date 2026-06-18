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
    ai_api_key: Optional[str] = None
    ai_model: str

@router.post("/settings/test-llm")
def test_llm_connection(req: TestLLMRequest):
    import ai
    try:
        content, reasoning_status = ai.test_llm_reasoning(req.ai_base_url, req.ai_api_key or "", req.ai_model)
        return {
            "success": True,
            "message": "连接成功！",
            "model_response": content,
            "reasoning_status": reasoning_status
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"测试连接失败: {str(e)}"
        }

class GetModelsRequest(BaseModel):
    ai_base_url: str
    ai_api_key: Optional[str] = None

@router.post("/settings/get-models")
def get_models(req: GetModelsRequest):
    import httpx
    url = f"{req.ai_base_url.rstrip('/')}/models"
    headers = {"Content-Type": "application/json"}
    if req.ai_api_key:
        headers["Authorization"] = f"Bearer {req.ai_api_key}"
        
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            
        if response.status_code != 200:
            return {
                "success": False,
                "message": f"获取模型列表失败，状态码 {response.status_code}: {response.text}"
            }
            
        result = response.json()
        
        # Check standard OpenAI format
        if "data" in result:
            models = [m["id"] for m in result["data"] if "id" in m]
            models.sort()
            return {"success": True, "models": models}
            
        # Check Ollama format
        if "models" in result:
            models = []
            for m in result["models"]:
                name = m.get("name") or m.get("model")
                if name:
                    models.append(name)
            models.sort()
            return {"success": True, "models": models}
            
        return {
            "success": False,
            "message": "解析模型列表响应失败，不支持的返回格式"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"获取模型列表失败: {str(e)}"
        }

@router.get("/settings/token-stats")
def get_token_stats():
    from db import get_db
    import crud
    with get_db() as conn:
        return crud.get_daily_token_stats(conn)
