import logging
import json
import db
import crud
from fastapi import APIRouter, HTTPException
from config import settings

logger = logging.getLogger("myrss.routers.profile")
router = APIRouter()

@router.get("/profile/interests")
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

@router.get("/profile/topic-detail")
def get_topic_detail(topic: str):
    if not settings.interest_profile_enabled:
        raise HTTPException(status_code=400, detail="Personalization profile is disabled")
        
    with db.get_db() as conn:
        detail = crud.get_topic_detail(conn, topic)
        if not detail:
            raise HTTPException(status_code=404, detail="Topic not found or no data available")
        return detail
