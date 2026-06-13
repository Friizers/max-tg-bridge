"""Хранилище связей MAX-чат <-> Telegram-ветка (topic).
Обычного SQLite для нагрузки моста с запасом достаточно."""
import sqlite3
import threading
from typing import Optional


class Storage:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS topic_map (
                    max_chat_id INTEGER PRIMARY KEY,
                    tg_topic_id INTEGER NOT NULL,
                    title       TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_topic ON topic_map(tg_topic_id);
                """
            )
            self.conn.commit()

    def get_topic(self, max_chat_id: int) -> Optional[int]:
        with self.lock:
            cur = self.conn.execute(
                "SELECT tg_topic_id FROM topic_map WHERE max_chat_id=?", (max_chat_id,)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set_topic(self, max_chat_id: int, tg_topic_id: int, title: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO topic_map(max_chat_id, tg_topic_id, title) "
                "VALUES (?, ?, ?)",
                (max_chat_id, tg_topic_id, title),
            )
            self.conn.commit()

    def get_chat_by_topic(self, tg_topic_id: int) -> Optional[int]:
        with self.lock:
            cur = self.conn.execute(
                "SELECT max_chat_id FROM topic_map WHERE tg_topic_id=?", (tg_topic_id,)
            )
            row = cur.fetchone()
            return row[0] if row else None
