import pytest
import sqlite3
import os
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from config import settings
import db
import crud
import ai
import maintenance
from ingester import RawEntry
from main import app

TEST_DB_PATH = "test_myrss_phase4.db"

@pytest.fixture(autouse=True)
def setup_test_db():
    settings.data["db_path"] = TEST_DB_PATH
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    db.init_db(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.fixture
def client():
    with patch("main.start_scheduler"), patch("main.shutdown_scheduler"):
        with TestClient(app) as c:
            yield c

def test_right_column_chat(client):
    # Setup database entry
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://example.com/rss", "Example Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g1", title="Article 1", url="https://example.com/1", author="Author", published_at="2026-06-05T00:00:00", raw_content="Fulltext content")
        ], cat_id)

    # Get entry ID
    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    entry_id = response.json()[0]["id"]

    # 1. Test Sync Chat
    mock_reply = "This is the sync reply from assistant."
    with patch("ai.generate_chat_response_sync", return_value=mock_reply) as mock_chat_sync:
        response = client.post(
            f"/entries/{entry_id}/chat?stream=false", 
            json={"message": "What is this article about?"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == mock_reply
        assert len(data["history"]) == 2
        assert data["history"][0]["role"] == "user"
        assert data["history"][0]["content"] == "What is this article about?"
        assert data["history"][1]["role"] == "assistant"
        assert data["history"][1]["content"] == mock_reply
        
        # Verify it was saved to DB
        with db.get_db() as conn:
            hist = crud.get_chat_history(conn, entry_id)
            assert len(hist) == 2
            assert hist[0]["role"] == "user"
            assert hist[1]["role"] == "assistant"

    # 2. Test Stream Chat
    mock_stream_chunks = [("This ", False), ("is ", False), ("the ", False), ("streaming ", False), ("assistant ", False), ("reply.", False)]
    with patch("ai.generate_chat_response_stream", return_value=iter(mock_stream_chunks)) as mock_chat_stream:
        response = client.post(
            f"/entries/{entry_id}/chat?stream=true", 
            json={"message": "Tell me more."}
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        
        # Parse stream events
        events = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
                
        assert len(events) > 0
        assert events[-1]["status"] == "done"
        
        # Verify DB chat history contains the user message and assistant full response
        with db.get_db() as conn:
            hist = crud.get_chat_history(conn, entry_id)
            # 2 messages from previous sync chat + 2 messages from stream chat = 4
            assert len(hist) == 4
            assert hist[2]["role"] == "user"
            assert hist[2]["content"] == "Tell me more."
            assert hist[3]["role"] == "assistant"
            assert hist[3]["content"] == "This is the streaming assistant reply."
            
            msg_to_delete_id = hist[0]["id"]

        # 3. Test Delete Chat Message
        response = client.delete(f"/chat-messages/{msg_to_delete_id}")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        
        # Verify it was deleted from DB
        with db.get_db() as conn:
            hist = crud.get_chat_history(conn, entry_id)
            assert len(hist) == 3
            assert msg_to_delete_id not in [h["id"] for h in hist]
            
        # Test deleting non-existent message
        response = client.delete("/chat-messages/99999")
        assert response.status_code == 404

def test_daily_maintenance_promotion(client):
    settings.data["classify"] = settings.data.get("classify", {})
    settings.data["classify"]["promote_threshold"] = 5
    
    # 1. Setup DB: feed and 6 uncategorized entries
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://test.com/rss", "Test Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        
        raw_entries = [
            RawEntry(guid=f"g{i}", title=f"iOS 20 updates part {i}", url=f"http://ios/{i}", author="A", published_at=f"2026-06-05T00:0{i}:00", raw_content="C")
            for i in range(6)
        ]
        crud.save_entries(conn, feed_id, raw_entries, cat_id)
        
        # Manually classify them into the default "未归类" category to represent daily fetch
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM entries WHERE feed_id = ?", (feed_id,))
        entry_rows = cursor.fetchall()
        entry_ids = [r["id"] for r in entry_rows]
        
        for eid in entry_ids:
            crud.update_entry_classification(conn, eid, cat_id, "skim")

    # 2. Mock AI identify_promotable_topics to promote these 6 entries
    mock_promotion = [
        {
            "category_name": "iOS 20",
            "entry_ids": entry_ids
        }
    ]
    
    with patch("ai.identify_promotable_topics", return_value=mock_promotion):
        # Trigger maintenance
        response = client.post("/maintenance")
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["ok"] is True
        
        # Verify category creation and entry migration
        with db.get_db() as conn:
            cats = crud.get_categories_for_feed(conn, feed_id)
            cat_names = {c["name"]: c["id"] for c in cats}
            
            assert "iOS 20" in cat_names
            
            # Check entries
            cursor = conn.cursor()
            cursor.execute("SELECT category_id FROM entries WHERE feed_id = ?", (feed_id,))
            entries_cat = cursor.fetchall()
            for entry in entries_cat:
                assert entry["category_id"] == cat_names["iOS 20"]

def test_update_entry_attention(client):
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://example.com/rss", "Example Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g1", title="Article 1", url="https://example.com/1", author="Author", published_at="2026-06-05T00:00:00", raw_content="C1")
        ], cat_id)

    # Get entry ID
    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    entry_id = response.json()[0]["id"]
    
    # 1. Update attention to "read"
    response = client.post(f"/entries/{entry_id}/attention", json={"attention": "read"})
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Verify updated in DB
    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    assert response.json()[0]["attention"] == "read"

    # 2. Update attention to "glance"
    response = client.post(f"/entries/{entry_id}/attention", json={"attention": "glance"})
    assert response.status_code == 200
    
    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    assert response.json()[0]["attention"] == "glance"

    # 3. Test invalid attention level
    response = client.post(f"/entries/{entry_id}/attention", json={"attention": "invalid_level"})
    assert response.status_code == 400
