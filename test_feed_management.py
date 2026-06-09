import pytest
import os
import xml.etree.ElementTree as ET
from unittest.mock import patch
from fastapi.testclient import TestClient

from config import settings
import db
import crud
import opml
from ingester import RawEntry
from main import app

TEST_DB_PATH = "test_feed_mgmt.db"

@pytest.fixture(autouse=True)
def setup_test_db():
    settings.data["db_path"] = TEST_DB_PATH
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    db.init_db(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.fixture(autouse=True)
def mock_settings_save():
    import copy
    orig_data = copy.deepcopy(settings.data)
    orig_path = settings.config_path
    
    with patch.object(settings, "save"):
        yield
        
    settings.data = orig_data
    settings.config_path = orig_path

@pytest.fixture
def client():
    with patch("main.start_scheduler"), patch("main.shutdown_scheduler"):
        with TestClient(app) as c:
            yield c

def test_update_feed(client):
    # Setup feed in DB
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://test.com/rss", "Original Title")
        
    # Update title
    response = client.put(f"/feeds/{feed_id}", json={"title": "Updated Title"})
    assert response.status_code == 200
    assert response.json()["title"] == "Updated Title"
    assert response.json()["enabled"] == 1

    # Disable feed
    response = client.put(f"/feeds/{feed_id}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] == 0

    # Verify state in list
    response = client.get("/feeds")
    assert response.status_code == 200
    feeds = response.json()
    assert len(feeds) == 1
    assert feeds[0]["title"] == "Updated Title"
    assert feeds[0]["enabled"] == 0

def test_delete_feed(client):
    # Setup feed with entries, summaries, chat messages, etc.
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://delete-me.com/rss", "To Delete")
        cat_id = crud.get_default_category(conn, feed_id)
        
        # Save an entry
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="guid-to-del", title="T1", url="L1", author="A1", published_at="2026-06-05T00:00:00", raw_content="C1")
        ], cat_id)
        
        # Get entry ID
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM entries WHERE feed_id = ?", (feed_id,))
        entry_id = cursor.fetchone()["id"]
        
        # Save fulltext, summary, chat message
        crud.save_fulltext(conn, entry_id, "Cleaned fulltext", "ok", "feed")
        crud.save_summary(conn, entry_id, "Summary text", "Note", "model")
        crud.save_chat_message(conn, entry_id, "user", "Hello?")

        # Assert data exists in DB before deletion
        cursor.execute("SELECT COUNT(*) as c FROM feeds WHERE id = ?", (feed_id,))
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM categories WHERE feed_id = ?", (feed_id,))
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM entries WHERE feed_id = ?", (feed_id,))
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM fulltext WHERE entry_id = ?", (entry_id,))
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM summaries WHERE entry_id = ?", (entry_id,))
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM chat_messages WHERE entry_id = ?", (entry_id,))
        assert cursor.fetchone()["c"] == 1

    # Call delete API
    response = client.delete(f"/feeds/{feed_id}")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    # Verify everything is cleaned up
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM feeds WHERE id = ?", (feed_id,))
        assert cursor.fetchone()["c"] == 0
        cursor.execute("SELECT COUNT(*) as c FROM categories WHERE feed_id = ?", (feed_id,))
        assert cursor.fetchone()["c"] == 0
        cursor.execute("SELECT COUNT(*) as c FROM entries WHERE feed_id = ?", (feed_id,))
        assert cursor.fetchone()["c"] == 0
        cursor.execute("SELECT COUNT(*) as c FROM fulltext WHERE entry_id = ?", (entry_id,))
        assert cursor.fetchone()["c"] == 0
        cursor.execute("SELECT COUNT(*) as c FROM summaries WHERE entry_id = ?", (entry_id,))
        assert cursor.fetchone()["c"] == 0
        cursor.execute("SELECT COUNT(*) as c FROM chat_messages WHERE entry_id = ?", (entry_id,))
        assert cursor.fetchone()["c"] == 0

def test_export_opml(client):
    # Setup two feeds in DB
    with db.get_db() as conn:
        crud.add_feed(conn, "https://feed1.com/rss", "Feed 1", "https://feed1.com")
        crud.add_feed(conn, "https://feed2.com/rss", "Feed 2")

    # Export OPML
    response = client.get("/export/opml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "kickrss_subscriptions.opml" in response.headers["content-disposition"]
    
    # Parse returned OPML XML
    xml_data = response.content
    root = ET.fromstring(xml_data)
    assert root.tag == "opml"
    
    outlines = root.findall(".//outline")
    assert len(outlines) == 2
    
    assert outlines[0].get("title") == "Feed 1"
    assert outlines[0].get("xmlUrl") == "https://feed1.com/rss"
    assert outlines[0].get("htmlUrl") == "https://feed1.com"
    
    assert outlines[1].get("title") == "Feed 2"
    assert outlines[1].get("xmlUrl") == "https://feed2.com/rss"
    assert outlines[1].get("htmlUrl") is None

def test_system_settings(client):
    # Test GET settings
    response = client.get("/settings")
    assert response.status_code == 200
    data = response.json()
    assert "fetch_interval_minutes" in data
    assert "ai_base_url" in data
    assert "ai_model" in data
    
    # Test PUT settings
    payload = {
        "fetch_interval_minutes": 20,
        "min_text_chars": 300,
        "promote_threshold": 8,
        "ai_base_url": "https://new-api.com/v1",
        "ai_api_key": "new-key",
        "ai_model": "new-model",
        "ai_pregenerate": True,
        "ai_stream": False,
        "chat_base_url": "https://chat-api.com/v1",
        "chat_api_key": "chat-key",
        "chat_model": "chat-model",
        "chat_max_tokens": 1500
    }
    with patch("scheduler.reschedule_refresh_job") as mock_reschedule:
        response = client.put("/settings", json=payload)
        assert response.status_code == 200
        updated = response.json()
        assert updated["fetch_interval_minutes"] == 20
        assert updated["min_text_chars"] == 300
        assert updated["promote_threshold"] == 8
        assert updated["ai_base_url"] == "https://new-api.com/v1"
        assert updated["ai_api_key"] == "new-key"
        assert updated["ai_model"] == "new-model"
        assert updated["ai_pregenerate"] is True
        assert updated["ai_stream"] is False
        assert updated["chat_base_url"] == "https://chat-api.com/v1"
        assert updated["chat_api_key"] == "chat-key"
        assert updated["chat_model"] == "chat-model"
        assert updated["chat_max_tokens"] == 1500
        
        # Verify scheduler rescheduling was called since interval changed
        mock_reschedule.assert_called_once_with(20)

