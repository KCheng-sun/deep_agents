"""SQLite 元数据存储（同步）。

管理笔记元数据、标签、关联关系、摄入日志的 CRUD 操作。
使用 sqlite3（线程安全），供 DeepAgents 工具在任意线程中直调。
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

from brain.models import (
    Connection,
    NoteMetadata,
    NoteStatus,
    RelationType,
    SourceType,
    Tag,
    TagCategory,
)


def _synchronized(method):
    """装饰器——用实例锁串行化数据库操作。

    LangGraph 的工具节点会并行执行多个工具，同一 SQLite 连接
    不能并发访问，必须加锁。
    """

    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class MetadataStore:
    """SQLite 元数据管理—notes / tags / note_tags / connections / ingestion_log。

    所有方法为同步调用，通过实例锁保证多线程安全。
    """

    def __init__(self, db_path: Path):
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ---- 生命周期 ----

    @_synchronized
    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        logger.info(f"MetadataStore 已连接: {self._db_path}")

    @_synchronized
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            logger.info("MetadataStore 已关闭")

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT,
                file_hash TEXT,
                content_preview TEXT DEFAULT '',
                content_length INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ingested_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                is_ai_generated INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS note_tags (
                note_id TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                confidence REAL,
                PRIMARY KEY (note_id, tag_id),
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_note_id TEXT NOT NULL,
                target_note_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                strength REAL DEFAULT 0.5,
                description TEXT,
                created_at TEXT NOT NULL,
                is_ai_generated INTEGER DEFAULT 0,
                FOREIGN KEY (source_note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ingestion_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id TEXT NOT NULL,
                event TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                duration_ms INTEGER,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新对话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,              -- 'user' | 'assistant'
                content TEXT NOT NULL,
                timeline TEXT DEFAULT '[]',      -- JSON: 工具调用轨迹 [{kind, name, args, done}]
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_fragments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'approved',  -- 'approved' | 'rejected'
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS digest_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,       -- 'daily' | 'weekly'
                report_date TEXT NOT NULL,       -- 报告日期（daily: 昨日日期; weekly: 周一日期）
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(report_type, report_date)
            );

            CREATE TABLE IF NOT EXISTS rss_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_fetched_at TEXT,
                entry_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS rss_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER NOT NULL,
                entry_id TEXT NOT NULL,          -- feed 条目的唯一 ID（去重）
                title TEXT NOT NULL,
                link TEXT DEFAULT '',
                note_id TEXT DEFAULT '',         -- 摄入后生成的笔记 ID
                published_at TEXT DEFAULT '',
                UNIQUE(feed_id, entry_id),
                FOREIGN KEY (feed_id) REFERENCES rss_feeds(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
            CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);
            CREATE INDEX IF NOT EXISTS idx_note_tags_note ON note_tags(note_id);
            CREATE INDEX IF NOT EXISTS idx_connections_source ON connections(source_note_id);
            CREATE INDEX IF NOT EXISTS idx_connections_target ON connections(target_note_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
        """)
        self._conn.commit()

    # ---- Notes CRUD ----

    @_synchronized
    def create_note(self, note: NoteMetadata) -> str:
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO notes (id, title, source_type, source_path, file_hash,
               content_preview, content_length, chunk_count, status,
               created_at, updated_at, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note.id, note.title, note.source_type.value, note.source_path,
                note.file_hash, note.content_preview, note.content_length,
                note.chunk_count, note.status.value, note.created_at,
                note.updated_at, note.ingested_at,
            ),
        )
        self._conn.commit()
        logger.debug(f"MetadataStore: 已创建笔记 {note.id} — {note.title}")
        return note.id

    @_synchronized
    def get_note(self, note_id: str) -> NoteMetadata | None:
        assert self._conn is not None
        row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_note(row)

    @_synchronized
    def list_notes(
        self, status: NoteStatus = NoteStatus.ACTIVE, limit: int = 50, offset: int = 0,
    ) -> list[NoteMetadata]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM notes WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status.value, limit, offset),
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    @_synchronized
    def update_note(self, note_id: str, **kwargs) -> None:
        assert self._conn is not None
        allowed = {"title", "content_preview", "content_length", "chunk_count",
                    "status", "file_hash", "updated_at", "ingested_at"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [note_id]
        self._conn.execute(f"UPDATE notes SET {set_clause} WHERE id = ?", values)
        self._conn.commit()

    @_synchronized
    def delete_note(self, note_id: str, soft: bool = True) -> None:
        assert self._conn is not None
        if soft:
            self._conn.execute("UPDATE notes SET status = ? WHERE id = ?",
                               (NoteStatus.DELETED.value, note_id))
        else:
            self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()
        logger.info(f"MetadataStore: 已{'软' if soft else '硬'}删除笔记 {note_id}")

    @_synchronized
    def note_exists(self, file_hash: str) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id FROM notes WHERE file_hash = ? AND status = 'active'",
            (file_hash,),
        ).fetchone()
        return row["id"] if row else None

    @_synchronized
    def count_notes(self, status: NoteStatus = NoteStatus.ACTIVE) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM notes WHERE status = ?", (status.value,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ---- Tags ----

    @_synchronized
    def get_or_create_tag(self, name: str, category: TagCategory, is_ai: bool = False) -> int:
        assert self._conn is not None
        row = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO tags (name, category, is_ai_generated) VALUES (?, ?, ?)",
            (name, category.value, int(is_ai)),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def add_tag_to_note(self, note_id: str, tag_id: int, confidence: float | None = None) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO note_tags (note_id, tag_id, confidence) VALUES (?, ?, ?)",
            (note_id, tag_id, confidence),
        )
        self._conn.commit()

    @_synchronized
    def get_note_tags(self, note_id: str) -> list[Tag]:
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT t.id, t.name, t.category, t.is_ai_generated, nt.confidence
               FROM tags t
               JOIN note_tags nt ON t.id = nt.tag_id
               WHERE nt.note_id = ?
               ORDER BY t.category, t.name""",
            (note_id,),
        ).fetchall()
        return [
            Tag(
                id=row["id"], name=row["name"],
                category=TagCategory(row["category"]) if row["category"] else TagCategory.TOPIC,
                is_ai_generated=bool(row["is_ai_generated"]),
                confidence=row["confidence"],
            ) for row in rows
        ]

    # ---- Connections ----

    @_synchronized
    def add_connection(self, conn: Connection) -> int:
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO connections
               (source_note_id, target_note_id, relation_type, strength,
                description, created_at, is_ai_generated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conn.source_note_id, conn.target_note_id, conn.relation_type.value,
             conn.strength, conn.description, conn.created_at, int(conn.is_ai_generated)),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_connections(self, note_id: str) -> list[Connection]:
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT * FROM connections
               WHERE source_note_id = ? OR target_note_id = ?
               ORDER BY strength DESC""",
            (note_id, note_id),
        ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    # ---- Ingestion Log ----

    @_synchronized
    def log_event(self, note_id: str, event: str, status: str,
                  message: str = "", duration_ms: int | None = None) -> None:
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO ingestion_log (note_id, event, status, message, duration_ms, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (note_id, event, status, message, duration_ms, datetime.now().isoformat()),
        )
        self._conn.commit()

    # ---- Sessions（会话） ----

    @_synchronized
    def create_session(self, session_id: str, title: str = "新对话") -> str:
        """创建会话。返回 session_id。"""
        assert self._conn is not None
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
        self._conn.commit()
        return session_id

    @_synchronized
    def list_sessions(self, limit: int = 50) -> list[dict]:
        """列出会话（按最近更新排序）。"""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    @_synchronized
    def get_session(self, session_id: str) -> dict | None:
        """获取会话详情。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @_synchronized
    def rename_session(self, session_id: str, title: str) -> None:
        """重命名会话并刷新 updated_at。"""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, datetime.now().isoformat(), session_id),
        )
        self._conn.commit()

    @_synchronized
    def touch_session(self, session_id: str) -> None:
        """刷新会话的 updated_at（有新消息时调用）。"""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id),
        )
        self._conn.commit()

    @_synchronized
    def delete_session(self, session_id: str) -> None:
        """删除会话（消息级联删除）。"""
        assert self._conn is not None
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    # ---- Messages（会话消息） ----

    @_synchronized
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        timeline: list | None = None,
    ) -> int:
        """保存一条消息。返回消息 ID。"""
        assert self._conn is not None
        import json

        timeline_json = json.dumps(timeline or [], ensure_ascii=False)
        cur = self._conn.execute(
            """INSERT INTO messages (session_id, role, content, timeline, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, timeline_json, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_messages(self, session_id: str) -> list[dict]:
        """获取会话的全部消息（按时间正序）。"""
        assert self._conn is not None
        import json

        rows = self._conn.execute(
            "SELECT id, role, content, timeline, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                timeline = json.loads(r["timeline"] or "[]")
            except json.JSONDecodeError:
                timeline = []
            result.append(
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "timeline": timeline,
                    "created_at": r["created_at"],
                }
            )
        return result

    @_synchronized
    def count_messages(self, session_id: str) -> int:
        """会话消息数。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ---- Knowledge Fragments（知识片段，HIL 确认后保存） ----

    @_synchronized
    def add_knowledge_fragment(
        self,
        title: str,
        content: str,
        session_id: str | None = None,
        status: str = "approved",
    ) -> int:
        """保存一条知识片段。返回片段 ID。"""
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO knowledge_fragments (session_id, title, content, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, title, content, status, datetime.now().isoformat()),
        )
        self._conn.commit()
        logger.info(f"MetadataStore: 知识片段已保存 — {title}")
        return cur.lastrowid

    @_synchronized
    def list_knowledge_fragments(self, limit: int = 50) -> list[dict]:
        """列出知识片段（按时间倒序）。"""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT id, session_id, title, content, status, created_at
               FROM knowledge_fragments
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "content": r["content"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    @_synchronized
    def find_similar_fragment(self, title: str) -> dict | None:
        """按标题查找已有知识片段（子智能体去重用）。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, title, content FROM knowledge_fragments WHERE title = ? LIMIT 1",
            (title,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "title": row["title"], "content": row["content"]}

    @_synchronized
    def delete_knowledge_fragment(self, fragment_id: int) -> bool:
        """删除知识片段。返回是否删除成功。"""
        assert self._conn is not None
        cur = self._conn.execute(
            "DELETE FROM knowledge_fragments WHERE id = ?", (fragment_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def search_knowledge_fragments(self, keyword: str, limit: int = 10) -> list[dict]:
        """按关键词模糊搜索知识片段（标题和内容）。"""
        assert self._conn is not None
        pattern = f"%{keyword}%"
        rows = self._conn.execute(
            """SELECT id, session_id, title, content, status, created_at
               FROM knowledge_fragments
               WHERE title LIKE ? OR content LIKE ?
               ORDER BY id DESC LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "content": r["content"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ---- Digest Reports（定时任务生成的摘要报告） ----

    @_synchronized
    def save_digest_report(self, report_type: str, report_date: str, content: str) -> int:
        """保存摘要报告（同类型同日期覆盖）。"""
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO digest_reports (report_type, report_date, content, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(report_type, report_date) DO UPDATE SET
                 content = excluded.content,
                 created_at = excluded.created_at""",
            (report_type, report_date, content, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_digest_report(self, report_type: str, report_date: str) -> dict | None:
        """按类型和日期获取摘要报告。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, report_type, report_date, content, created_at FROM digest_reports WHERE report_type = ? AND report_date = ?",
            (report_type, report_date),
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def list_digest_reports(self, limit: int = 10) -> list[dict]:
        """列出最近摘要报告。"""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, report_type, report_date, content, created_at FROM digest_reports ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- RSS Feeds ----

    @_synchronized
    def add_rss_feed(self, url: str) -> int:
        """添加 RSS 源。返回 feed_id。"""
        assert self._conn is not None
        cur = self._conn.execute(
            "INSERT INTO rss_feeds (url, created_at) VALUES (?, ?)",
            (url, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def list_rss_feeds(self) -> list[dict]:
        """列出全部 RSS 源。"""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, url, title, created_at, last_fetched_at, entry_count FROM rss_feeds ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    @_synchronized
    def get_rss_feed(self, feed_id: int) -> dict | None:
        """获取单个 RSS 源。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, url, title, created_at, last_fetched_at, entry_count FROM rss_feeds WHERE id = ?",
            (feed_id,),
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def delete_rss_feed(self, feed_id: int) -> bool:
        """删除 RSS 源（条目级联删除）。"""
        assert self._conn is not None
        cur = self._conn.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def update_rss_feed_after_fetch(
        self,
        feed_id: int,
        title: str,
        new_entries: int,
    ) -> None:
        """拉取后更新源信息。"""
        assert self._conn is not None
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE rss_feeds SET title = ?, last_fetched_at = ?, entry_count = entry_count + ? WHERE id = ?",
            (title, now, new_entries, feed_id),
        )
        self._conn.commit()

    @_synchronized
    def rss_entry_exists(self, feed_id: int, entry_id: str) -> bool:
        """检查 feed 条目是否已处理过。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 FROM rss_entries WHERE feed_id = ? AND entry_id = ?",
            (feed_id, entry_id),
        ).fetchone()
        return row is not None

    @_synchronized
    def add_rss_entry(
        self,
        feed_id: int,
        entry_id: str,
        title: str,
        link: str,
        published: str,
        note_id: str = "",
    ) -> int:
        """记录一条已处理的 feed 条目。"""
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO rss_entries (feed_id, entry_id, title, link, note_id, published_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (feed_id, entry_id, title, link, note_id, published),
        )
        self._conn.commit()
        return cur.lastrowid

    # ---- Helpers ----

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> NoteMetadata:
        return NoteMetadata(
            id=row["id"], title=row["title"],
            source_type=SourceType(row["source_type"]) if row["source_type"] else SourceType.MARKDOWN,
            source_path=row["source_path"], file_hash=row["file_hash"],
            content_preview=row["content_preview"] or "",
            content_length=row["content_length"] or 0,
            chunk_count=row["chunk_count"] or 0,
            status=NoteStatus(row["status"]) if row["status"] else NoteStatus.ACTIVE,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            ingested_at=row["ingested_at"],
        )

    @staticmethod
    def _row_to_connection(row: sqlite3.Row) -> Connection:
        return Connection(
            id=row["id"], source_note_id=row["source_note_id"],
            target_note_id=row["target_note_id"],
            relation_type=RelationType(row["relation_type"]) if row["relation_type"] else RelationType.RELATED,
            strength=row["strength"] or 0.5, description=row["description"],
            is_ai_generated=bool(row["is_ai_generated"]),
            created_at=row["created_at"] or "",
        )
