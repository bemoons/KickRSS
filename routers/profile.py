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
            
        # Get activity timestamps (last 30 days)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT recorded_at 
            FROM engagement 
            WHERE recorded_at IS NOT NULL AND datetime(recorded_at) >= datetime('now', '-30 days')
        """)
        activity_rows = cursor.fetchall()
        activity_timestamps = [r[0] for r in activity_rows]
        
        # Get category distribution
        cursor.execute("""
            SELECT COALESCE(c.name, '未分类') as category_name, COUNT(e.id) as read_count
            FROM engagement g
            JOIN entries e ON g.entry_id = e.id
            LEFT JOIN categories c ON e.category_id = c.id
            GROUP BY e.category_id
            ORDER BY read_count DESC
        """)
        category_rows = cursor.fetchall()
        category_distribution = [{"name": r[0], "count": r[1]} for r in category_rows]
        
        return {
            "snapshot_date": latest["snapshot_date"],
            "total_articles": latest["total_articles"],
            "high_engagement": latest["high_engagement"],
            "low_engagement": latest["low_engagement"],
            "topics": topics,
            "attention_guide": latest["prompt_text"],
            "activity_timestamps": activity_timestamps,
            "category_distribution": category_distribution
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
