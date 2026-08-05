import logging
import json
import datetime
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
        cursor = conn.cursor()
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
            
        # Get token stats for the last 7 calendar days
        token_stats = []
        today = datetime.date.today()
        for i in range(6, -1, -1):
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            cursor.execute("SELECT total_tokens FROM token_usage WHERE date = ?", (d,))
            row = cursor.fetchone()
            total_tokens = row[0] if row else 0
            token_stats.append({
                "date": d,
                "total_tokens": total_tokens
            })
        
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
            "token_stats": token_stats,
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
