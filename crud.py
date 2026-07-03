import logging
import datetime
from typing import List, Optional, Dict, Any
import sqlite3
import re
import lxml.html
import trafilatura
from config import settings
from ingester import RawEntry

logger = logging.getLogger(__name__)

def html_to_markdown(html_content: str) -> str:
    if not html_content:
        return ""
    # If it doesn't look like HTML (no tags), just return as-is
    if "<" not in html_content or ">" not in html_content:
        return html_content
    try:
        # Wrap in a div to ensure a single root, and parse
        wrapped = f"<div>{html_content}</div>"
        root = lxml.html.fromstring(wrapped)
        
        def convert_element(el) -> str:
            tag = el.tag
            text = el.text or ""
            
            # Process children
            children_text = ""
            for child in el.iterchildren():
                children_text += convert_element(child)
                if child.tail:
                    children_text += child.tail
            
            inner = text + children_text
            
            if tag == 'p':
                return f"\n\n{inner.strip()}\n\n"
            elif tag in ['br', 'hr']:
                return "\n"
            elif tag in ['strong', 'b']:
                return f"**{inner.strip()}**"
            elif tag in ['em', 'i']:
                return f"*{inner.strip()}*"
            elif tag == 'a':
                href = el.get('href', '')
                return f"[{inner.strip()}]({href})" if inner.strip() else href
            elif tag == 'img':
                src = el.get('src', '')
                alt = el.get('alt', '') or el.get('title', '') or 'image'
                if src:
                    return f"\n\n![{alt}]({src})\n\n"
                return ""
            elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(tag[1])
                hashes = "#" * level
                return f"\n\n{hashes} {inner.strip()}\n\n"
            elif tag == 'li':
                return f"\n* {inner.strip()}"
            elif tag in ['ul', 'ol']:
                return f"\n{inner}\n"
            elif tag == 'blockquote':
                return f"\n\n> {inner.strip()}\n\n"
            elif tag in ['code', 'pre']:
                return f"`{inner.strip()}`"
            else:
                return inner
                
        md = convert_element(root)
        md = re.sub(r'\n{3,}', '\n\n', md)
        return md.strip()
    except Exception as e:
        logger.warning(f"Error converting HTML to Markdown: {e}")
        return html_content

def clean_html(html_content: str) -> str:
    return html_to_markdown(html_content)

def get_feed_by_url(conn: sqlite3.Connection, url: str) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM feeds WHERE url = ?", (url,))
    return cursor.fetchone()

def get_feed_by_id(conn: sqlite3.Connection, feed_id: int) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,))
    return cursor.fetchone()

def add_feed(conn: sqlite3.Connection, url: str, title: str, site_url: str = None) -> int:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO feeds (title, url, site_url, seeded) VALUES (?, ?, ?, 0)",
            (title, url, site_url)
        )
        feed_id = cursor.lastrowid
        
        # Every feed must have a default category named "未归类"
        cursor.execute(
            "INSERT INTO categories (feed_id, name, is_default, created_at) VALUES (?, ?, 1, ?)",
            (feed_id, "未归类", datetime.datetime.now(datetime.timezone.utc).isoformat())
        )
        return feed_id
    except sqlite3.IntegrityError:
        logger.warning(f"Feed URL {url} already exists.")
        # Retrieve existing feed ID
        cursor.execute("SELECT id FROM feeds WHERE url = ?", (url,))
        row = cursor.fetchone()
        return row["id"]

def get_default_category(conn: sqlite3.Connection, feed_id: int) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM categories WHERE feed_id = ? AND is_default = 1", (feed_id,))
    row = cursor.fetchone()
    if row:
        return row["id"]
    # Fallback/Safety: Create it if it somehow doesn't exist
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO categories (feed_id, name, is_default, created_at) VALUES (?, '未归类', 1, ?)",
        (feed_id, now_str)
    )
    return cursor.lastrowid

def list_feeds(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    # Return feeds with unread counts
    cursor.execute("""
        SELECT f.id, f.title, f.url, f.site_url, f.last_fetched_at, f.enabled, f.need_classification,
               COALESCE(SUM(CASE WHEN e.is_read = 0 THEN 1 ELSE 0 END), 0) as unread_count
        FROM feeds f
        LEFT JOIN entries e ON e.feed_id = f.id
        GROUP BY f.id
    """)
    return cursor.fetchall()

def get_categories_for_feed(conn: sqlite3.Connection, feed_id: int) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.feed_id, c.name, c.is_default, c.created_at,
               COALESCE(SUM(CASE WHEN e.is_read = 0 THEN 1 ELSE 0 END), 0) as unread_count
        FROM categories c
        LEFT JOIN entries e ON e.category_id = c.id
        WHERE c.feed_id = ?
        GROUP BY c.id
    """, (feed_id,))
    return cursor.fetchall()

def get_entries_for_category(
    conn: sqlite3.Connection, 
    category_id: int, 
    unread_only: bool = True, 
    limit: int = 50, 
    offset: int = 0
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    if unread_only:
        cursor.execute("""
            SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                   attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
            FROM entries
            WHERE category_id = ? AND is_read = 0
            ORDER BY published_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (category_id, limit, offset))
    else:
        cursor.execute("""
            SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                   attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
            FROM entries
            WHERE category_id = ?
            ORDER BY published_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (category_id, limit, offset))
    return cursor.fetchall()

def get_entries_for_feed(
    conn: sqlite3.Connection, 
    feed_id: int, 
    unread_only: bool = True, 
    limit: int = 50, 
    offset: int = 0
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    if unread_only:
        cursor.execute("""
            SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                   attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
            FROM entries
            WHERE feed_id = ? AND is_read = 0
            ORDER BY published_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (feed_id, limit, offset))
    else:
        cursor.execute("""
            SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                   attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
            FROM entries
            WHERE feed_id = ?
            ORDER BY published_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (feed_id, limit, offset))
    return cursor.fetchall()

def get_unread_entries(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.id, e.feed_id, e.category_id, e.guid, e.title, e.url, e.author, e.published_at, e.fetched_at,
               e.attention, e.likely_no_text, e.fulltext_ready, e.is_read, e.read_at, e.classified_at, e.is_starred,
               f.title as feed_title
        FROM entries e
        JOIN feeds f ON e.feed_id = f.id
        WHERE e.is_read = 0
        ORDER BY e.published_at DESC, e.id DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    return cursor.fetchall()

def save_entries(
    conn: sqlite3.Connection, 
    feed_id: int, 
    raw_entries: List[RawEntry], 
    category_id: int
) -> int:
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    min_chars = settings.min_text_chars
    new_count = 0

    for entry in raw_entries:
        # Check if guid already exists for this feed
        cursor.execute("SELECT id, raw_content, fulltext_ready FROM entries WHERE feed_id = ? AND guid = ?", (feed_id, entry.guid))
        existing = cursor.fetchone()
        if existing:
            existing_id, existing_content, existing_fulltext_ready = existing
            new_content = entry.raw_content or ""
            # Self-healing: If existing content lacks fulltext and feed has updated with longer text, update it
            if not existing_fulltext_ready and len(new_content) > len(existing_content or ""):
                fulltext_ready = 1 if len(new_content) >= min_chars else 0
                if fulltext_ready == 1:
                    cursor.execute("""
                        UPDATE entries 
                        SET raw_content = ?, fulltext_ready = ?, likely_no_text = 0
                        WHERE id = ?
                    """, (new_content, fulltext_ready, existing_id))
                else:
                    cursor.execute("""
                        UPDATE entries 
                        SET raw_content = ?, fulltext_ready = ?
                        WHERE id = ?
                    """, (new_content, fulltext_ready, existing_id))
                
                # If fulltext is now ready, clean and cache it
                if fulltext_ready == 1:
                    clean_content = clean_html(new_content)
                    status = "ok" if len(clean_content) >= min_chars else "no_text"
                    cursor.execute("SELECT entry_id FROM fulltext WHERE entry_id = ?", (existing_id,))
                    if cursor.fetchone():
                        cursor.execute("""
                            UPDATE fulltext 
                            SET content = ?, status = ?, fetched_at = ?, fetcher = 'feed'
                            WHERE entry_id = ?
                        """, (clean_content, status, now_str, existing_id))
                    else:
                        cursor.execute("""
                            INSERT INTO fulltext (entry_id, content, status, fetched_at, fetcher)
                            VALUES (?, ?, ?, ?, 'feed')
                        """, (existing_id, clean_content, status, now_str))
            continue

        raw_content = entry.raw_content or ""
        raw_content_len = len(raw_content)
        
        # Decide fulltext_ready and likely_no_text
        if getattr(entry, "likely_no_text", 0) or getattr(entry, "fulltext_ready", 0):
            likely_no_text = entry.likely_no_text
            fulltext_ready = entry.fulltext_ready
        else:
            fulltext_ready = 1 if raw_content_len >= min_chars else 0
            content_lower = raw_content.lower()
            likely_no_text = 0
            if raw_content_len < min_chars and ("<video" in content_lower or "<iframe" in content_lower):
                likely_no_text = 1

        # Insert entry
        cursor.execute("""
            INSERT INTO entries (
                feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                raw_content, attention, likely_no_text, fulltext_ready, is_read
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            feed_id, category_id, entry.guid, entry.title, entry.url, entry.author,
            entry.published_at, now_str, raw_content, "skim", likely_no_text, fulltext_ready
        ))
        
        entry_id = cursor.lastrowid
        new_count += 1

        # If fulltext is ready (feed has full text), clean and cache it
        if fulltext_ready == 1:
            if likely_no_text == 1:
                cursor.execute("""
                    INSERT INTO fulltext (entry_id, content, status, fetched_at, fetcher)
                    VALUES (?, '此文章主要包含视频/多媒体内容，无正文可提取。请点击标题或右上角链接查看原始视频。', 'video', ?, 'feed')
                """, (entry_id, now_str))
            else:
                clean_content = clean_html(raw_content)
                status = "ok" if len(clean_content) >= min_chars else "no_text"
                cursor.execute("""
                    INSERT INTO fulltext (entry_id, content, status, fetched_at, fetcher)
                    VALUES (?, ?, ?, ?, 'feed')
                """, (entry_id, clean_content, status, now_str))

    return new_count

def update_feed_fetch_status(
    conn: sqlite3.Connection, 
    feed_id: int, 
    etag: Optional[str], 
    last_modified: Optional[str]
):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        UPDATE feeds 
        SET etag = ?, last_modified = ?, last_fetched_at = ?
        WHERE id = ?
    """, (etag, last_modified, now_str, feed_id))

def mark_entry_read(conn: sqlite3.Connection, entry_id: int) -> bool:
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("UPDATE entries SET is_read = 1, read_at = ? WHERE id = ?", (now_str, entry_id))
    return cursor.rowcount > 0

def mark_entry_unread(conn: sqlite3.Connection, entry_id: int) -> bool:
    cursor = conn.cursor()
    cursor.execute("UPDATE entries SET is_read = 0, read_at = NULL WHERE id = ?", (entry_id,))
    return cursor.rowcount > 0

def mark_entries_read(conn: sqlite3.Connection, entry_ids: List[int]) -> int:
    if not entry_ids:
        return 0
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Build dynamic placeholders
    placeholders = ",".join("?" for _ in entry_ids)
    cursor.execute(
        f"UPDATE entries SET is_read = 1, read_at = ? WHERE id IN ({placeholders})",
        [now_str] + entry_ids
    )
    return cursor.rowcount

def mark_entries_unread(conn: sqlite3.Connection, entry_ids: List[int]) -> int:
    if not entry_ids:
        return 0
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in entry_ids)
    cursor.execute(
        f"UPDATE entries SET is_read = 0, read_at = NULL WHERE id IN ({placeholders})",
        entry_ids
    )
    return cursor.rowcount

def mark_category_read(conn: sqlite3.Connection, category_id: int) -> List[int]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM entries WHERE category_id = ? AND is_read = 0",
        (category_id,)
    )
    ids = [row[0] for row in cursor.fetchall()]
    if ids:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(
            f"UPDATE entries SET is_read = 1, read_at = ? WHERE id IN ({placeholders})",
            [now_str] + ids
        )
    return ids

def mark_feed_read(conn: sqlite3.Connection, feed_id: int) -> List[int]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM entries WHERE feed_id = ? AND is_read = 0",
        (feed_id,)
    )
    ids = [row[0] for row in cursor.fetchall()]
    if ids:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(
            f"UPDATE entries SET is_read = 1, read_at = ? WHERE id IN ({placeholders})",
            [now_str] + ids
        )
    return ids

def get_entry_fulltext(conn: sqlite3.Connection, entry_id: int) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM fulltext WHERE entry_id = ?", (entry_id,))
    return cursor.fetchone()

def get_entry_by_id(conn: sqlite3.Connection, entry_id: int) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
    return cursor.fetchone()

def save_categories(conn: sqlite3.Connection, feed_id: int, names: List[str]):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for name in names:
        try:
            cursor.execute(
                "INSERT INTO categories (feed_id, name, is_default, created_at) VALUES (?, ?, 0, ?)",
                (feed_id, name.strip(), now_str)
            )
        except sqlite3.IntegrityError:
            # Category already exists for this feed, skip
            pass

def update_entry_classification(
    conn: sqlite3.Connection, 
    entry_id: int, 
    category_id: int, 
    attention: str
):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        UPDATE entries 
        SET category_id = ?, attention = ?, classified_at = ?
        WHERE id = ?
    """, (category_id, attention, now_str, entry_id))

def update_entry_attention(conn: sqlite3.Connection, entry_id: int, attention: str):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE entries 
        SET attention = ?
        WHERE id = ?
    """, (attention, entry_id))
    
    # Write/update engagement.manual_bump
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("SELECT 1 FROM engagement WHERE entry_id = ?", (entry_id,))
    exists = cursor.fetchone()
    if exists:
        cursor.execute("""
            UPDATE engagement
            SET manual_bump = ?, recorded_at = ?
            WHERE entry_id = ?
        """, (attention, now_str, entry_id))
    else:
        cursor.execute("""
            INSERT INTO engagement (entry_id, opened, active_dwell_ms, scrolled_pct, scrolled_to_bottom, opened_original, favorited, manual_bump, recorded_at)
            VALUES (?, 0, 0, 0.0, 0, 0, (SELECT is_starred FROM entries WHERE id = ?), ?, ?)
        """, (entry_id, entry_id, attention, now_str))

def get_unclassified_entries(conn: sqlite3.Connection, feed_id: int) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, raw_content 
        FROM entries 
        WHERE feed_id = ? AND classified_at IS NULL
        ORDER BY published_at DESC
        LIMIT 100
    """, (feed_id,))
    return cursor.fetchall()

def get_entry_summary(conn: sqlite3.Connection, entry_id: int) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM summaries WHERE entry_id = ?", (entry_id,))
    return cursor.fetchone()

def delete_summary(conn: sqlite3.Connection, entry_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM summaries WHERE entry_id = ?", (entry_id,))


def save_summary(
    conn: sqlite3.Connection, 
    entry_id: int, 
    content: str, 
    clickbait_note: Optional[str], 
    model: str
):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO summaries (entry_id, content, clickbait_note, model, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (entry_id, content, clickbait_note, model, now_str))

def save_translation(
    conn: sqlite3.Connection, 
    entry_id: int, 
    content: str, 
    lang: str
):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO translations (entry_id, content, lang, created_at)
        VALUES (?, ?, ?, ?)
    """, (entry_id, content, lang, now_str))

def get_entry_translation(conn: sqlite3.Connection, entry_id: int) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM translations WHERE entry_id = ?", (entry_id,))
    return cursor.fetchone()

def delete_translation(conn: sqlite3.Connection, entry_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM translations WHERE entry_id = ?", (entry_id,))

def save_paragraph_translation(
    conn: sqlite3.Connection,
    entry_id: int,
    para_index: int,
    lang: str,
    original_text: str,
    translated_text: str
):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO paragraph_translations (entry_id, para_index, lang, original_text, translated_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (entry_id, para_index, lang, original_text, translated_text, now_str))

def get_paragraph_translation(
    conn: sqlite3.Connection,
    entry_id: int,
    para_index: int,
    lang: str
) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM paragraph_translations 
        WHERE entry_id = ? AND para_index = ? AND lang = ?
    """, (entry_id, para_index, lang))
    return cursor.fetchone()

def delete_paragraph_translations(conn: sqlite3.Connection, entry_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM paragraph_translations WHERE entry_id = ?", (entry_id,))

def save_fulltext(
    conn: sqlite3.Connection, 
    entry_id: int, 
    content: str, 
    status: str, 
    fetcher: str
):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 1. Insert or replace fulltext cache
    cursor.execute("""
        INSERT OR REPLACE INTO fulltext (entry_id, content, status, fetched_at, fetcher)
        VALUES (?, ?, ?, ?, ?)
    """, (entry_id, content, status, now_str, fetcher))
    
    # 2. Update entries table setting fulltext_ready = 1 (and likely_no_text = 0 if status is ok)
    if status == "ok":
        cursor.execute("""
            UPDATE entries 
            SET fulltext_ready = 1, likely_no_text = 0 
            WHERE id = ?
        """, (entry_id,))
    elif status == "video":
        cursor.execute("""
            UPDATE entries 
            SET fulltext_ready = 1, likely_no_text = 1 
            WHERE id = ?
        """, (entry_id,))
    else:
        cursor.execute("""
            UPDATE entries 
            SET fulltext_ready = 1 
            WHERE id = ?
        """, (entry_id,))

def save_chat_message(conn: sqlite3.Connection, entry_id: int, role: str, content: str):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO chat_messages (entry_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (entry_id, role, content, now_str))

def get_chat_history(conn: sqlite3.Connection, entry_id: int) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, role, content, created_at 
        FROM chat_messages 
        WHERE entry_id = ? 
        ORDER BY id ASC
    """, (entry_id,))
    return cursor.fetchall()

def delete_chat_message(conn: sqlite3.Connection, message_id: int) -> bool:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_messages WHERE id = ?", (message_id,))
    return cursor.rowcount > 0

def get_recent_uncategorized_entries(
    conn: sqlite3.Connection, 
    feed_id: int, 
    days: int = 14
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    cutoff_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    cursor.execute("""
        SELECT e.id, e.title 
        FROM entries e
        JOIN categories c ON e.category_id = c.id
        WHERE e.feed_id = ? AND c.is_default = 1
          AND e.fetched_at >= ?
    """, (feed_id, cutoff_date))
    return cursor.fetchall()

def move_entries_to_category(conn: sqlite3.Connection, entry_ids: List[int], category_id: int) -> int:
    if not entry_ids:
        return 0
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in entry_ids)
    cursor.execute(
        f"UPDATE entries SET category_id = ? WHERE id IN ({placeholders})",
        [category_id] + entry_ids
    )
    return cursor.rowcount

def reset_uncategorized_entries_classification(conn: sqlite3.Connection, feed_id: Optional[int] = None):
    cursor = conn.cursor()
    if feed_id is not None:
        cursor.execute("""
            UPDATE entries 
            SET classified_at = NULL 
            WHERE feed_id = ? 
              AND category_id IN (SELECT id FROM categories WHERE is_default = 1)
              AND classified_at IS NOT NULL
        """, (feed_id,))
    else:
        cursor.execute("""
            UPDATE entries 
            SET classified_at = NULL 
            WHERE category_id IN (SELECT id FROM categories WHERE is_default = 1)
              AND classified_at IS NOT NULL
        """)

def search_entries(
    conn: sqlite3.Connection,
    query: str,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return []
        
    conditions = []
    params = []
    for w in words:
        like_pat = f"%{w}%"
        conditions.append("(e.title LIKE ? OR e.raw_content LIKE ? OR f.content LIKE ? OR cm.content LIKE ?)")
        params.extend([like_pat, like_pat, like_pat, like_pat])
        
    where_clause = " AND ".join(conditions)
    
    if unread_only:
        sql = f"""
            SELECT DISTINCT e.id, e.feed_id, e.category_id, e.guid, e.title, e.url, e.author, e.published_at, e.fetched_at,
                   e.attention, e.likely_no_text, e.fulltext_ready, e.is_read, e.read_at, e.classified_at, e.is_starred
            FROM entries e
            LEFT JOIN fulltext f ON f.entry_id = e.id
            LEFT JOIN chat_messages cm ON cm.entry_id = e.id
            WHERE e.is_read = 0 AND ({where_clause})
            ORDER BY e.published_at DESC, e.id DESC
            LIMIT ? OFFSET ?
        """
    else:
        sql = f"""
            SELECT DISTINCT e.id, e.feed_id, e.category_id, e.guid, e.title, e.url, e.author, e.published_at, e.fetched_at,
                   e.attention, e.likely_no_text, e.fulltext_ready, e.is_read, e.read_at, e.classified_at, e.is_starred
            FROM entries e
            LEFT JOIN fulltext f ON f.entry_id = e.id
            LEFT JOIN chat_messages cm ON cm.entry_id = e.id
            WHERE ({where_clause})
            ORDER BY e.published_at DESC, e.id DESC
            LIMIT ? OFFSET ?
        """
        
    params.append(limit)
    params.append(offset)
    cursor.execute(sql, tuple(params))
    return cursor.fetchall()

def update_feed_title(conn: sqlite3.Connection, feed_id: int, title: str) -> bool:
    cursor = conn.cursor()
    cursor.execute("UPDATE feeds SET title = ? WHERE id = ?", (title, feed_id))
    return cursor.rowcount > 0

def update_feed_enabled(conn: sqlite3.Connection, feed_id: int, enabled: bool) -> bool:
    cursor = conn.cursor()
    cursor.execute("UPDATE feeds SET enabled = ? WHERE id = ?", (1 if enabled else 0, feed_id))
    return cursor.rowcount > 0

def update_feed_need_classification(conn: sqlite3.Connection, feed_id: int, need_classification: bool) -> bool:
    cursor = conn.cursor()
    val = 1 if need_classification else 0
    cursor.execute("UPDATE feeds SET need_classification = ? WHERE id = ?", (val, feed_id))
    if not need_classification:
        default_cat_id = get_default_category(conn, feed_id)
        cursor.execute("UPDATE entries SET category_id = ?, classified_at = NULL WHERE feed_id = ?", (default_cat_id, feed_id))
        cursor.execute("DELETE FROM categories WHERE feed_id = ? AND is_default = 0", (feed_id,))
    return cursor.rowcount > 0

def delete_feed(conn: sqlite3.Connection, feed_id: int) -> bool:
    cursor = conn.cursor()
    # Check if feed exists
    cursor.execute("SELECT 1 FROM feeds WHERE id = ?", (feed_id,))
    if not cursor.fetchone():
        return False
    
    # 1. Delete chat messages
    cursor.execute("""
        DELETE FROM chat_messages 
        WHERE entry_id IN (SELECT id FROM entries WHERE feed_id = ?)
    """, (feed_id,))
    
    # 2. Delete summaries
    cursor.execute("""
        DELETE FROM summaries 
        WHERE entry_id IN (SELECT id FROM entries WHERE feed_id = ?)
    """, (feed_id,))
    
    # 3. Delete fulltext
    cursor.execute("""
        DELETE FROM fulltext 
        WHERE entry_id IN (SELECT id FROM entries WHERE feed_id = ?)
    """, (feed_id,))
    
    # 4. Delete entries
    cursor.execute("DELETE FROM entries WHERE feed_id = ?", (feed_id,))
    
    # 5. Delete categories
    cursor.execute("DELETE FROM categories WHERE feed_id = ?", (feed_id,))
    
    # 6. Delete feed
    cursor.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    
    return True

def update_entry_starred(conn: sqlite3.Connection, entry_id: int, is_starred: bool) -> bool:
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat() if is_starred else None
    cursor.execute("""
        UPDATE entries 
        SET is_starred = ?, starred_at = ?
        WHERE id = ?
    """, (1 if is_starred else 0, now_str, entry_id))
    
    if cursor.rowcount > 0:
        # Sync with engagement table if record exists
        cursor.execute("""
            UPDATE engagement
            SET favorited = ?, recorded_at = datetime('now')
            WHERE entry_id = ?
        """, (1 if is_starred else 0, entry_id))
        return True
    return False

def get_starred_entries(
    conn: sqlite3.Connection, 
    unread_only: bool = False, 
    limit: int = 50, 
    offset: int = 0
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    if unread_only:
        cursor.execute("""
            SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                   attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
            FROM entries
            WHERE is_starred = 1 AND is_read = 0
            ORDER BY published_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    else:
        cursor.execute("""
            SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
                   attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
            FROM entries
            WHERE is_starred = 1
            ORDER BY published_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    return cursor.fetchall()

def get_starred_entries_count(conn: sqlite3.Connection) -> Dict[str, int]:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM entries WHERE is_starred = 1 AND is_read = 0")
    unread = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM entries WHERE is_starred = 1")
    total = cursor.fetchone()[0]
    return {"unread_count": unread, "total_count": total}

def record_engagement(conn: sqlite3.Connection, entry_id: int, active_dwell_ms: int, scrolled_pct: float, opened_original: bool):
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    scrolled_to_bottom = 1 if scrolled_pct >= 0.9 else 0
    
    # Check if starred/favorited from entries
    cursor.execute("SELECT is_starred FROM entries WHERE id = ?", (entry_id,))
    row = cursor.fetchone()
    favorited = row[0] if row else 0
    
    cursor.execute("SELECT active_dwell_ms, scrolled_pct, scrolled_to_bottom, opened_original FROM engagement WHERE entry_id = ?", (entry_id,))
    existing = cursor.fetchone()
    
    if existing:
        new_dwell = existing[0] + active_dwell_ms
        new_pct = max(existing[1], scrolled_pct)
        new_to_bottom = max(existing[2], scrolled_to_bottom)
        new_opened_orig = max(existing[3], 1 if opened_original else 0)
        
        cursor.execute("""
            UPDATE engagement
            SET opened = 1,
                active_dwell_ms = ?,
                scrolled_pct = ?,
                scrolled_to_bottom = ?,
                opened_original = ?,
                favorited = ?,
                recorded_at = ?
            WHERE entry_id = ?
        """, (new_dwell, new_pct, new_to_bottom, new_opened_orig, favorited, now_str, entry_id))
    else:
        cursor.execute("""
            INSERT INTO engagement (entry_id, opened, active_dwell_ms, scrolled_pct, scrolled_to_bottom, opened_original, favorited, manual_bump, recorded_at)
            VALUES (?, 1, ?, ?, ?, ?, ?, NULL, ?)
        """, (entry_id, active_dwell_ms, scrolled_pct, scrolled_to_bottom, 1 if opened_original else 0, favorited, now_str))

def get_latest_user_interest(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM user_interests
        ORDER BY snapshot_date DESC LIMIT 1
    """)
    return cursor.fetchone()

def get_topic_detail(conn: sqlite3.Connection, topic_name: str) -> Optional[Dict[str, Any]]:
    row = get_latest_user_interest(conn)
    if not row:
        return None
    
    import json
    try:
        topics = json.loads(row["topics_json"])
    except Exception:
        return None
        
    high_interest = topics.get("high_interest", [])
    low_interest = topics.get("low_interest", [])
    
    topic_item = None
    for item in high_interest + low_interest:
        if item.get("topic") == topic_name:
            topic_item = item
            break
            
    if not topic_item:
        return None
        
    entry_ids = topic_item.get("entry_ids", [])
    if not entry_ids:
        return {
            "topic": topic_name,
            "stats": {"article_count": 0, "favorite_count": 0, "original_count": 0},
            "weekly_trend": [0] * 12,
            "articles": []
        }
        
    placeholders = ",".join("?" for _ in entry_ids)
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT e.id as entry_id, e.title, f.title as source, e.is_starred, e.published_at,
               g.opened_original, g.active_dwell_ms
        FROM entries e
        JOIN feeds f ON e.feed_id = f.id
        LEFT JOIN engagement g ON g.entry_id = e.id
        WHERE e.id IN ({placeholders})
    """, tuple(entry_ids))
    
    rows = cursor.fetchall()
    
    articles = []
    favorite_count = 0
    original_count = 0
    
    import datetime
    today = datetime.date.today()
    weekly_trend = [0] * 12
    
    for r in rows:
        d = dict(r)
        
        badges = []
        if d["is_starred"]:
            badges.append("favorited")
            favorite_count += 1
        if d["opened_original"]:
            badges.append("opened_original")
            original_count += 1
            
        art_info = {
            "entry_id": d["entry_id"],
            "title": d["title"],
            "source": d["source"],
            "badges": badges
        }
        articles.append(art_info)
        
        pub_at_str = d["published_at"]
        if pub_at_str:
            try:
                pub_date_str = pub_at_str[:10]
                pub_date = datetime.datetime.strptime(pub_date_str, "%Y-%m-%d").date()
                day_diff = (today - pub_date).days
                if day_diff < 0:
                    day_diff = 0
                week_index = 11 - (day_diff // 7)
                if 0 <= week_index < 12:
                    weekly_trend[week_index] += 1
            except Exception:
                pass
                
    return {
        "topic": topic_name,
        "stats": {
            "article_count": len(rows),
            "favorite_count": favorite_count,
            "original_count": original_count
        },
        "weekly_trend": weekly_trend,
        "articles": articles
    }

def record_token_usage(conn, prompt_tokens: int, completion_tokens: int, total_tokens: int):
    import datetime
    date_str = datetime.date.today().strftime('%Y-%m-%d')
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO token_usage (date, prompt_tokens, completion_tokens, total_tokens)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            prompt_tokens = prompt_tokens + excluded.prompt_tokens,
            completion_tokens = completion_tokens + excluded.completion_tokens,
            total_tokens = total_tokens + excluded.total_tokens
    """, (date_str, prompt_tokens, completion_tokens, total_tokens))

def get_daily_token_stats(conn) -> dict:
    import datetime
    date_str = datetime.date.today().strftime('%Y-%m-%d')
    cursor = conn.cursor()
    cursor.execute("SELECT prompt_tokens, completion_tokens, total_tokens FROM token_usage WHERE date = ?", (date_str,))
    row = cursor.fetchone()
    if row:
        return {
            "date": date_str,
            "prompt_tokens": row[0],
            "completion_tokens": row[1],
            "total_tokens": row[2]
        }
    return {
        "date": date_str,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0
    }

def get_notes_entries(
    conn: sqlite3.Connection, 
    limit: int = 50, 
    offset: int = 0
) -> List[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, feed_id, category_id, guid, title, url, author, published_at, fetched_at,
               attention, likely_no_text, fulltext_ready, is_read, read_at, classified_at, is_starred
        FROM entries
        WHERE id IN (SELECT DISTINCT entry_id FROM chat_messages WHERE content IS NOT NULL AND trim(content) != '')
        ORDER BY published_at DESC, id DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    return cursor.fetchall()

def get_notes_entries_count(conn: sqlite3.Connection) -> Dict[str, int]:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT entry_id) FROM chat_messages WHERE content IS NOT NULL AND trim(content) != ''")
    total = cursor.fetchone()[0]
    return {"total_count": total}

def delete_entry_chat_history(conn: sqlite3.Connection, entry_id: int) -> bool:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_messages WHERE entry_id = ?", (entry_id,))
    return cursor.rowcount > 0

