import pytest
import sqlite3
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from config import settings
import db
import crud
import ai
import classifier
from ingester import FeedparserIngester, RawEntry, FetchResult
from main import app

TEST_DB_PATH = "test_myrss_phase2.db"

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

def test_ai_seeding_and_classification(client):
    # Setup mocks for network and AI
    mock_entries = [
        RawEntry(guid="g1", title="New iPhone 18 released", url="http://apple", author="Apple", published_at="2026-06-05T00:00:00", raw_content="Details about iPhone 18"),
        RawEntry(guid="g2", title="How to cook a perfect egg", url="http://cooking", author="Chef", published_at="2026-06-05T01:00:00", raw_content="Egg cooking tips"),
        RawEntry(guid="g3", title="Unrelated random topic", url="http://random", author="Random", published_at="2026-06-05T02:00:00", raw_content="Some thoughts"),
    ]
    mock_fetch_result = FetchResult(
        entries=mock_entries,
        etag="etag1",
        last_modified="lm1",
        status_code=200,
        feed_title="Mock tech & life feed",
        site_url="http://mock.com"
    )
    
    # Mock category seeding
    mock_categories = ["Tech", "Cooking"]
    
    # Mock classification batch results
    def mock_classify_batch(allowed_categories, entries):
        # We simulate the AI response
        results = []
        for e in entries:
            if "iPhone" in e["title"]:
                results.append({"id": e["id"], "category": "Tech", "attention": "read"})
            elif "egg" in e["title"]:
                results.append({"id": e["id"], "category": "Cooking", "attention": "skim"})
            else:
                results.append({"id": e["id"], "category": "未归类", "attention": "glance"})
        return results

    with patch.object(FeedparserIngester, "fetch_new", return_value=mock_fetch_result), \
         patch("ai.generate_seed_categories", return_value=mock_categories) as mock_seed_call, \
         patch("ai.classify_entries_batch", side_effect=mock_classify_batch) as mock_classify_call:
        
        # Add feed (background task runs synchronously in TestClient)
        response = client.post("/feeds", json={"url": "https://techcooking.com/rss.xml"})
        assert response.status_code == 200
        feed_id = response.json()["id"]
        
        # Verify seeding was triggered with titles
        mock_seed_call.assert_called_once()
        # Verify classification was called
        mock_classify_call.assert_called_once()
        
        # Verify categories in DB
        with db.get_db() as conn:
            cats = crud.get_categories_for_feed(conn, feed_id)
            cat_names = {c["name"]: c["id"] for c in cats}
            assert "Tech" in cat_names
            assert "Cooking" in cat_names
            assert "未归类" in cat_names
            
            # Verify entries classification
            # Fetch entries from DB
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, category_id, attention FROM entries WHERE feed_id = ?", (feed_id,))
            entries_db = cursor.fetchall()
            assert len(entries_db) == 3
            
            for entry in entries_db:
                if "iPhone" in entry["title"]:
                    assert entry["category_id"] == cat_names["Tech"]
                    assert entry["attention"] == "read"
                elif "egg" in entry["title"]:
                    assert entry["category_id"] == cat_names["Cooking"]
                    assert entry["attention"] == "skim"
                else:
                    assert entry["category_id"] == cat_names["未归类"]
                    assert entry["attention"] == "glance"

def test_classification_fallback(client):
    # Setup mock with failing batch classifier
    mock_entries = [
        RawEntry(guid="g1", title="Article 1", url="L1", author="A1", published_at="2026-06-05T00:00:00", raw_content="C1"),
    ]
    mock_fetch_result = FetchResult(
        entries=mock_entries,
        etag="etag1",
        last_modified="lm1",
        status_code=200,
        feed_title="Mock Feed",
        site_url="http://mock.com"
    )

    with patch.object(FeedparserIngester, "fetch_new", return_value=mock_fetch_result), \
         patch("ai.generate_seed_categories", return_value=["Category A"]), \
         patch("ai.call_chat_completion", side_effect=Exception("API Error")):
        
        # Adding feed should succeed because classification is run with fallbacks and background isolation
        response = client.post("/feeds", json={"url": "https://fallback-test.com/rss.xml"})
        assert response.status_code == 200
        feed_id = response.json()["id"]
        
        # Verify entry is classified as "未归类" and "skim" (defaults on AI fail)
        with db.get_db() as conn:
            cats = crud.get_categories_for_feed(conn, feed_id)
            cat_names = {c["name"]: c["id"] for c in cats}
            
            cursor = conn.cursor()
            cursor.execute("SELECT category_id, attention FROM entries WHERE feed_id = ?", (feed_id,))
            entry = cursor.fetchone()
            
            assert entry["category_id"] == cat_names["未归类"]
            assert entry["attention"] == "skim"
