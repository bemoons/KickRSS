import pytest
import sqlite3
import os
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from config import settings
import db
import crud
import extractor
import ai
from ingester import RawEntry
from main import app

TEST_DB_PATH = "test_myrss_phase3.db"

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

def test_lazy_load_fulltext_and_streaming_summary(client):
    extracted_text = "This is the actual long full-text body of the article talking about general programming and not clickbait AI. We are repeating this content to make sure it passes the minimum character threshold configured in settings. Min chars is 200, so this text must be sufficiently long to be recognized as valid content instead of failing the length check."

    # Setup database entry
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://example.com/rss", "Example Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        # Entry with raw_content set directly
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g1", title="Misleading Title about AI", url="https://example.com/ai-article", author="Author", published_at="2026-06-05T00:00:00", raw_content=extracted_text)
        ], cat_id)

    # Get entry ID
    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    entry_id = response.json()[0]["id"]

    # Call fulltext API - should fetch and clean raw content
    response = client.get(f"/entries/{entry_id}/fulltext")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["content"] == extracted_text
    
    # Verify it is cached in DB
    with db.get_db() as conn:
        ft = crud.get_entry_fulltext(conn, entry_id)
        assert ft is not None
        assert ft["content"] == extracted_text
        assert ft["status"] == "ok"

    # Mock AI streaming summary response
    # The format is: CLICKBAIT_NOTE: ... \n SUMMARY: ...
    ai_raw_chunks = [
        "CLICKBAIT_NOTE: ", "The title mentions AI, ", "but the article is actually about general programming.\n",
        "SUMMARY: ", "- This is a summary chunk.\n", "- Another bullet point."
    ]

    with patch("ai.generate_summary_stream", return_value=iter(ai_raw_chunks)):
        # Fetch summary (streaming mode)
        response = client.get(f"/entries/{entry_id}/summary?stream=true")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        
        # Parse SSE stream chunks
        events = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
                
        # We expect streaming chunks
        assert len(events) > 0
        assert any(e["clickbait_note"] is not None for e in events)
        assert any("summary chunk" in e["summary"] for e in events)
        assert events[-1]["status"] == "done"

        # Verify it was cached in summaries DB
        with db.get_db() as conn:
            summary_db = crud.get_entry_summary(conn, entry_id)
            assert summary_db is not None
            assert "summary chunk" in summary_db["content"]
            assert "programming" in summary_db["clickbait_note"]

        # Call summary API again (cached), should return immediately
        response2 = client.get(f"/entries/{entry_id}/summary?stream=false")
        assert response2.status_code == 200
        assert response2.json()["status"] == "ok"
        assert "summary chunk" in response2.json()["summary"]
        assert "programming" in response2.json()["clickbait_note"]

def test_no_text_empty_crawling(client):
    # Setup database entry
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://example.com/rss", "Example Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g2", title="Pure Video Post", url="https://example.com/video", author="Author", published_at="2026-06-05T00:00:00", raw_content="Brief video...")
        ], cat_id)

    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    entry_id = response.json()[0]["id"]

    # Mock empty fulltext extraction (length < 200 min_text_chars)
    with patch("extractor.trafilatura.fetch_url", return_value="<html>HTML</html>"), \
         patch("extractor.trafilatura.extract", return_value="Too short text"):
        
        # Fetching summary should detect no text and fallback without calling AI
        with patch("ai.generate_summary_stream") as mock_stream_ai:
            response = client.get(f"/entries/{entry_id}/summary?stream=false")
            assert response.status_code == 200
            assert response.json()["status"] == "no_text"
            assert "无正文可总结" in response.json()["summary"]
            
            # Verify AI was NOT called
            mock_stream_ai.assert_not_called()

def test_pregeneration_logic():
    # Setup DB entries
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://example.com/rss", "Example Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        
        # Save a long content (fulltext_ready = 1) entry
        long_content = "Z" * 300
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g3", title="Highly important article", url="https://example.com/read-article", author="Author", published_at="2026-06-05T00:00:00", raw_content=long_content)
        ], cat_id)

        # Get the entry
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM entries WHERE guid = 'g3'")
        entry_id = cursor.fetchone()["id"]
        
        # Manually set attention = 'read' (as if classified by AI in Phase 2)
        crud.update_entry_classification(conn, entry_id, cat_id, "read")

    # Set pregenerate config to True
    settings.data["ai"] = settings.data.get("ai", {})
    settings.data["ai"]["pregenerate"] = True

    # Mock AI summary sync response
    mock_ai_response = "CLICKBAIT_NOTE: NONE\nSUMMARY: This is a pregenerated summary."
    with patch("ai.generate_summary_sync", return_value=mock_ai_response):
        # Trigger pregeneration
        from classifier import pregenerate_summaries_for_feed
        pregenerate_summaries_for_feed(feed_id)
        
        # Verify it was pregenerated and cached in DB
        with db.get_db() as conn:
            summary_db = crud.get_entry_summary(conn, entry_id)
            assert summary_db is not None
            assert summary_db["content"] == "This is a pregenerated summary."
            assert summary_db["clickbait_note"] is None
