import aiosqlite
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db = None

    async def connect(self):
        self.db = await aiosqlite.connect("bot.db")
        self.db.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info("Connected to SQLite")

    async def _create_tables(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_full_name TEXT,
                user_telegram_username TEXT,
                custom_username TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                admin_message_id INTEGER,
                admin_chat_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                custom_username TEXT NOT NULL
            );
        """)
        await self.db.commit()

    async def set_user_custom_username(self, user_id: int, custom_username: str):
        await self.db.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, custom_username) VALUES (?, ?)",
            (user_id, custom_username)
        )
        await self.db.commit()

    async def remove_user_custom_username(self, user_id: int):
        await self.db.execute("DELETE FROM user_settings WHERE user_id=?", (user_id,))
        await self.db.commit()

    async def get_user_custom_username(self, user_id: int) -> Optional[str]:
        cursor = await self.db.execute(
            "SELECT custom_username FROM user_settings WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        return row["custom_username"] if row else None

    async def add_request(self, user_id: int, full_name: str, telegram_username: str,
                          custom_username: str, amount: int) -> int:
        cursor = await self.db.execute(
            """INSERT INTO requests
               (user_id, user_full_name, user_telegram_username, custom_username, amount)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, full_name, telegram_username, custom_username, amount)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def update_admin_message(self, request_id: int, admin_chat_id: int, admin_message_id: int):
        await self.db.execute(
            "UPDATE requests SET admin_chat_id=?, admin_message_id=? WHERE id=?",
            (admin_chat_id, admin_message_id, request_id)
        )
        await self.db.commit()

    async def complete_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        cursor = await self.db.execute(
            "UPDATE requests SET status='completed', completed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            (request_id,)
        )
        await self.db.commit()
        if cursor.rowcount == 0:
            return None
        cursor = await self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_user_requests(self, user_id: int, status: str = "completed") -> List[Dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM requests WHERE user_id=? AND status=? ORDER BY created_at DESC",
            (user_id, status)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all_requests(self, status: str = "completed") -> List[Dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM requests WHERE status=? ORDER BY created_at DESC",
            (status,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def close(self):
        if self.db:
            await self.db.close()