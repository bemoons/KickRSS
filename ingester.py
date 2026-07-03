import logging
import datetime
import time
from typing import List, Optional, Protocol
from dataclasses import dataclass
import feedparser
import httpx

logger = logging.getLogger(__name__)

@dataclass
class RawEntry:
    guid: str
    title: str
    url: Optional[str]
    author: Optional[str]
    published_at: Optional[str]
    raw_content: Optional[str]
    likely_no_text: int = 0
    fulltext_ready: int = 0

@dataclass
class FetchResult:
    entries: List[RawEntry]
    etag: Optional[str]
    last_modified: Optional[str]
    status_code: int
    feed_title: Optional[str] = None
    site_url: Optional[str] = None
    not_modified: bool = False

class Ingester(Protocol):
    def fetch_new(
        self, 
        feed_url: str, 
        etag: Optional[str] = None, 
        last_modified: Optional[str] = None
    ) -> FetchResult:
        ...

    def fetch_seed(self, feed_url: str, n: int = 100) -> List[RawEntry]:
        ...

class FeedparserIngester:
    def __init__(self, timeout_seconds: int = 15):
        self.timeout_seconds = timeout_seconds

    def fetch_new(
        self, 
        feed_url: str, 
        etag: Optional[str] = None, 
        last_modified: Optional[str] = None
    ) -> FetchResult:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        try:
            # Using httpx to perform conditional request
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.get(feed_url, headers=headers)
                
            if response.status_code == 304:
                logger.info(f"Feed {feed_url} not modified (304)")
                return FetchResult(
                    entries=[],
                    etag=etag,
                    last_modified=last_modified,
                    status_code=304,
                    not_modified=True
                )
            
            response.raise_for_status()
            
            # Extract new headers
            new_etag = response.headers.get("ETag")
            new_last_modified = response.headers.get("Last-Modified")
            
            # Parse feed content
            parsed = feedparser.parse(response.content)
            
            # Extract entries
            raw_entries = self._parse_feed_entries(parsed)
            
            # Extract feed metadata
            feed_title = None
            site_url = None
            if hasattr(parsed, "feed"):
                feed_title = parsed.feed.get("title")
                site_url = parsed.feed.get("link")
            
            return FetchResult(
                entries=raw_entries,
                etag=new_etag or etag,
                last_modified=new_last_modified or last_modified,
                status_code=response.status_code,
                feed_title=feed_title,
                site_url=site_url
            )

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error fetching feed {feed_url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}", exc_info=True)
            raise

    def fetch_seed(self, feed_url: str, n: int = 100) -> List[RawEntry]:
        """
        Fetch up to `n` entries for seeding, ignoring etag/last-modified headers.
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.get(feed_url, headers=headers)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            raw_entries = self._parse_feed_entries(parsed)
            return raw_entries[:n]
        except Exception as e:
            logger.error(f"Error seeding feed {feed_url}: {e}", exc_info=True)
            raise

    def _parse_feed_entries(self, parsed: dict) -> List[RawEntry]:
        raw_entries = []
        for entry in parsed.entries:
            # guid: id, fallback to link
            guid = entry.get("id") or entry.get("link")
            if not guid:
                logger.warning("Entry missing both id and link, skipping.")
                continue

            title = entry.get("title", "No Title")
            url = entry.get("link")
            author = entry.get("author")
            # Parse publication date
            published_at = None
            published_parsed = entry.get("published_parsed")
            if published_parsed:
                try:
                    dt = datetime.datetime(*published_parsed[:6], tzinfo=datetime.timezone.utc)
                    published_at = dt.isoformat()
                except Exception:
                    pass
            
            if not published_at:
                # Fallback to raw published text or current UTC time
                published_at = entry.get("published") or datetime.datetime.now(datetime.timezone.utc).isoformat()

            # Content extraction: prefer content[0].value, fallback to summary
            raw_content = None
            content_list = entry.get("content")
            if content_list and isinstance(content_list, list):
                raw_content = content_list[0].get("value")
            if not raw_content:
                raw_content = entry.get("summary")

            # Check for custom type (e.g. Huxiu <type>video_article</type>)
            custom_type = entry.get("type")
            is_type_video = custom_type in ("video_article", "video")
            likely_no_text = 1 if is_type_video else 0
            fulltext_ready = 1 if is_type_video else 0

            raw_entries.append(
                RawEntry(
                    guid=guid,
                    title=title,
                    url=url,
                    author=author,
                    published_at=published_at,
                    raw_content=raw_content,
                    likely_no_text=likely_no_text,
                    fulltext_ready=fulltext_ready
                )
            )
        return raw_entries
