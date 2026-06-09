import sqlite3
import contextlib
import logging
from pathlib import Path
from config import settings

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    site_url        TEXT,
    etag            TEXT,
    last_modified   TEXT,
    last_fetched_at TEXT,
    seeded          INTEGER NOT NULL DEFAULT 0,   -- 是否已完成冷启动播种
    enabled         INTEGER NOT NULL DEFAULT 1,
    need_classification INTEGER NOT NULL DEFAULT 1  -- 是否启用 AI 自动分类
);

-- 每源的抽屉(分类)。含一个不可删的 "未归类"
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id     INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0,        -- 1 = "未归类" 兜底抽屉
    created_at  TEXT,
    UNIQUE(feed_id, name)
);

CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id       INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    category_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,  -- 归类结果
    guid          TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT,
    author        TEXT,
    published_at  TEXT,
    fetched_at    TEXT,
    raw_content   TEXT,                 -- feed 自带内容(可能截断)
    attention     TEXT,                 -- read | skim | glance
    likely_no_text INTEGER DEFAULT 0,   -- 抓取时粗筛:疑似无正文
    fulltext_ready INTEGER NOT NULL DEFAULT 0, -- 全文是否已就绪(feed 自带够长=1;导语源待现抓=0)
    is_read       INTEGER NOT NULL DEFAULT 0,
    read_at       TEXT,
    classified_at TEXT,
    is_starred    INTEGER NOT NULL DEFAULT 0,   -- 收藏状态
    UNIQUE(feed_id, guid)
);

CREATE INDEX IF NOT EXISTS idx_entries_cat ON entries(category_id, is_read);
CREATE INDEX IF NOT EXISTS idx_entries_feed_unread ON entries(feed_id, is_read);

-- 懒加载:全文缓存
CREATE TABLE IF NOT EXISTS fulltext (
    entry_id   INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    content    TEXT,                    -- 提取到的正文;空/极短表示无正文
    status     TEXT,                    -- ok | no_text | fetch_failed
    fetched_at TEXT,
    fetcher    TEXT                     -- feed | trafilatura | rendering_service
);

-- 懒加载:单篇摘要缓存
CREATE TABLE IF NOT EXISTS summaries (
    entry_id   INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    clickbait_note TEXT,                -- 若标题与正文不符的点破说明,可空
    model      TEXT,
    created_at TEXT
);

-- 右栏对话:按 entry 维度存多轮
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id   INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,           -- user | assistant
    content    TEXT NOT NULL,
    created_at TEXT
);

-- 懒加载:单篇原文翻译缓存 (沉浸式段落对照)
CREATE TABLE IF NOT EXISTS translations (
    entry_id   INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,           -- 翻译后的全文本
    lang       TEXT NOT NULL,           -- 目标语言代码
    created_at TEXT
);

-- 单段对照翻译缓存 (段落对照流式翻译)
CREATE TABLE IF NOT EXISTS paragraph_translations (
    entry_id        INTEGER NOT NULL,
    para_index      INTEGER NOT NULL,
    lang            TEXT NOT NULL,
    original_text   TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    created_at      TEXT,
    PRIMARY KEY (entry_id, para_index, lang),
    FOREIGN KEY (entry_id) REFERENCES entries (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS engagement (
    entry_id           INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    opened             INTEGER NOT NULL DEFAULT 0,
    active_dwell_ms    INTEGER NOT NULL DEFAULT 0,
    scrolled_pct       REAL NOT NULL DEFAULT 0.0,
    scrolled_to_bottom INTEGER NOT NULL DEFAULT 0,
    opened_original    INTEGER NOT NULL DEFAULT 0,
    favorited          INTEGER NOT NULL DEFAULT 0,
    manual_bump        TEXT,
    recorded_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_interests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL UNIQUE,
    total_articles  INTEGER NOT NULL DEFAULT 0,
    high_engagement INTEGER NOT NULL DEFAULT 0,
    low_engagement  INTEGER NOT NULL DEFAULT 0,
    topics_json     TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    generated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_fetched_at ON entries(fetched_at);
"""

@contextlib.contextmanager
def get_db(db_path: str = None):
    if db_path is None:
        db_path = settings.db_path
    
    # Ensure parent directories exist
    db_file_path = Path(db_path)
    db_file_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_file_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path: str = None):
    if db_path is None:
        db_path = settings.db_path
    logger.info(f"Initializing database at {db_path}")
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA)
        
        # Check and migrate schema if database already exists but misses new columns
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(entries);")
        columns = [row[1] for row in cursor.fetchall()]
        if "is_starred" not in columns:
            logger.info("Migrating database: adding is_starred column to entries table")
            cursor.execute("ALTER TABLE entries ADD COLUMN is_starred INTEGER NOT NULL DEFAULT 0;")
        
        if "starred_at" not in columns:
            logger.info("Migrating database: adding starred_at column to entries table")
            try:
                cursor.execute("ALTER TABLE entries ADD COLUMN starred_at TEXT;")
            except Exception as e:
                logger.error(f"Failed to add starred_at column: {e}")
        
        # Create index now that is_starred is guaranteed to exist
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_starred ON entries(is_starred);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_fetched_at ON entries(fetched_at);")
        
        # Check and migrate feeds table
        cursor.execute("PRAGMA table_info(feeds);")
        feed_columns = [row[1] for row in cursor.fetchall()]
        if "need_classification" not in feed_columns:
            logger.info("Migrating database: adding need_classification column to feeds table")
            cursor.execute("ALTER TABLE feeds ADD COLUMN need_classification INTEGER NOT NULL DEFAULT 1;")
            
        logger.info("Database schema initialized successfully")
