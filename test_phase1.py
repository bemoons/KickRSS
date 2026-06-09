import pytest
import json
import sqlite3
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from config import settings
import db
import crud
import opml
from ingester import FeedparserIngester, RawEntry, FetchResult
from main import app

# Use a test database path
TEST_DB_PATH = "test_myrss.db"

@pytest.fixture(autouse=True)
def setup_test_db():
    # Override database path in settings
    settings.data["db_path"] = TEST_DB_PATH
    # Ensure fresh DB before each test
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    db.init_db(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.fixture
def client():
    # Return a TestClient instance, bypassing lifespan scheduler startup to avoid background loops during tests
    with patch("main.start_scheduler"), patch("main.shutdown_scheduler"):
        with TestClient(app) as c:
            yield c

def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

def test_opml_parsing():
    opml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <opml version="1.0">
        <head><title>Test Feeds</title></head>
        <body>
            <outline text="Tech" title="Tech">
                <outline type="rss" text="IT Home" title="IT Home" xmlUrl="https://www.ithome.com/rss/" htmlUrl="https://www.ithome.com/"/>
            </outline>
            <outline type="rss" text="Blog" title="Blog" xmlUrl="https://example.com/feed" htmlUrl="https://example.com"/>
        </body>
    </opml>
    """
    feeds = opml.parse_opml(opml_data.encode("utf-8"))
    assert len(feeds) == 2
    assert feeds[0]["title"] == "IT Home"
    assert feeds[0]["url"] == "https://www.ithome.com/rss/"
    assert feeds[0]["site_url"] == "https://www.ithome.com/"
    assert feeds[1]["title"] == "Blog"
    assert feeds[1]["url"] == "https://example.com/feed"

def test_add_feed_and_list(client):
    # Mock FeedparserIngester.fetch_new to avoid hitting the actual network
    mock_entries = [
        RawEntry(guid="guid1", title="Article 1", url="http://link1", author="Author1", published_at="2026-06-05T00:00:00", raw_content="Hello World"),
        RawEntry(guid="guid2", title="Article 2", url="http://link2", author="Author2", published_at="2026-06-05T01:00:00", raw_content="Short")
    ]
    mock_result = FetchResult(
        entries=mock_entries,
        etag="test-etag",
        last_modified="test-lm",
        status_code=200,
        feed_title="Mock Feed",
        site_url="http://mockfeed.com"
    )

    with patch.object(FeedparserIngester, "fetch_new", return_value=mock_result), \
         patch("ai.generate_seed_categories", return_value=[]), \
         patch("main.classify_feed_entries") as mock_classify:
        # Add a feed (background tasks run synchronously in TestClient)
        response = client.post("/feeds", json={"url": "https://example.com/feed.xml"})
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://example.com/feed.xml"
        feed_id = data["id"]

        # Check that categories exist
        response = client.get(f"/feeds/{feed_id}/categories")
        assert response.status_code == 200
        cats = response.json()
        assert len(cats) == 1
        assert cats[0]["name"] == "未归类"
        assert cats[0]["is_default"] == 1
        assert cats[0]["unread_count"] == 2 # 2 entries added by cold start

        # Check feeds list
        response = client.get("/feeds")
        assert response.status_code == 200
        feeds = response.json()
        assert len(feeds) == 1
        assert feeds[0]["unread_count"] == 2
        
        # Check feed title got updated by background seeding
        assert feeds[0]["title"] == "Mock Feed"

def test_read_operations(client):
    # Setup simple feed directly in DB
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://test.com/rss", "Test Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        
        # Insert 3 unread entries
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g1", title="T1", url="L1", author="A1", published_at="2026-06-05T00:00:00", raw_content="C1"),
            RawEntry(guid="g2", title="T2", url="L2", author="A2", published_at="2026-06-05T01:00:00", raw_content="C2"),
            RawEntry(guid="g3", title="T3", url="L3", author="A3", published_at="2026-06-05T02:00:00", raw_content="C3"),
        ], cat_id)

    # 1. Verify entries count
    response = client.get(f"/categories/{cat_id}/entries?unread=1")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 3

    # Get entry ids
    e1_id = entries[2]["id"] # order is desc published_at, so g1 is index 2
    e2_id = entries[1]["id"]
    e3_id = entries[0]["id"]

    # 2. Mark single entry read
    response = client.post(f"/entries/{e1_id}/read")
    assert response.status_code == 200
    
    # 3. Check unread count
    response = client.get(f"/categories/{cat_id}/entries?unread=1")
    assert len(response.json()) == 2

    # 4. Mark multiple entries read
    response = client.post("/entries/read", json={"ids": [e2_id, e3_id]})
    assert response.status_code == 200
    assert response.json()["count"] == 2

    # 5. Check unread count is 0
    response = client.get(f"/categories/{cat_id}/entries?unread=1")
    assert len(response.json()) == 0

    # 6. Mark single entry back to unread
    response = client.post(f"/entries/{e1_id}/unread")
    assert response.status_code == 200
    
    # 7. Check unread count is 1 again
    response = client.get(f"/categories/{cat_id}/entries?unread=1")
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == e1_id

    # 8. Mark all read again
    response = client.post("/entries/read", json={"ids": [e1_id, e2_id, e3_id]})
    assert response.status_code == 200
    assert "ids" in response.json()
    
    # 9. Mark multiple entries back to unread (batch undo)
    response = client.post("/entries/unread", json={"ids": [e1_id, e2_id]})
    assert response.status_code == 200
    
    # 10. Check unread count is 2
    response = client.get(f"/categories/{cat_id}/entries?unread=1")
    assert len(response.json()) == 2

def test_fulltext_and_stubs(client):
    with db.get_db() as conn:
        feed_id = crud.add_feed(conn, "https://test.com/rss", "Test Feed")
        cat_id = crud.get_default_category(conn, feed_id)
        
        # Raw content length >= 200 (settings.min_text_chars)
        long_content = "X" * 250
        short_content = "Short content"
        
        crud.save_entries(conn, feed_id, [
            RawEntry(guid="g1", title="T1", url="L1", author="A1", published_at="2026-06-05T00:00:00", raw_content=long_content),
            RawEntry(guid="g2", title="T2", url="L2", author="A2", published_at="2026-06-05T01:00:00", raw_content=short_content),
        ], cat_id)

    # Get entries
    response = client.get(f"/categories/{cat_id}/entries?unread=0")
    entries = response.json()
    
    # Check fulltext_ready flag
    assert entries[0]["fulltext_ready"] == 0 # g2 is short_content
    assert entries[1]["fulltext_ready"] == 1 # g1 is long_content

    # Get fulltext for g1 (which is long_content, should be cleaned and cached in fulltext)
    g1_id = entries[1]["id"]
    response = client.get(f"/entries/{g1_id}/fulltext")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["content"] == long_content

    # Get fulltext for g2 (short content, fulltext_ready was 0, should use cleaned raw content directly)
    g2_id = entries[0]["id"]
    response = client.get(f"/entries/{g2_id}/fulltext")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["content"] == short_content

    # Check summary
    with patch("ai.generate_summary_stream", return_value=iter(["SUMMARY: Mock Summary"])):
        response = client.get(f"/entries/{g1_id}/summary")
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except Exception as je:
                    logger.error(f"Failed to parse SSE JSON: {line[5:]!r}")
                    raise je
        assert len(events) > 0

    # Check chat
    with patch("ai.generate_chat_response_sync", return_value="Mock Chat Reply"):
        response = client.post(f"/entries/{g1_id}/chat?stream=false", json={"message": "hello"})
        assert response.status_code == 200
        assert "Mock Chat" in response.json()["reply"]
