"""SQLite-backed account storage."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from .storage import AccountStorage

logger = logging.getLogger(__name__)


class SqliteStorage(AccountStorage):
    """
    SQLite-backed account state persistence.

    Requires ``aiosqlite`` package::

        pip install 'wechat-agent-sdk[sqlite]'

    Uses a single file with table ``account_state(account_id, token, cursor, meta)``.
    """

    def __init__(self, db_path: str = "~/.wechat-agent-sdk/accounts.db"):
        self._db_path = str(Path(db_path).expanduser())
        self._db: Any = None

    async def _ensure_db(self) -> Any:
        if self._db is None:
            try:
                import aiosqlite
            except ImportError:
                raise ImportError(
                    "aiosqlite package required. Install: pip install 'wechat-agent-sdk[sqlite]'"
                )
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(str(path))
            await self._db.execute(
                "CREATE TABLE IF NOT EXISTS account_state "
                "(account_id TEXT PRIMARY KEY, token TEXT, cursor TEXT, meta TEXT)"
            )
            await self._db.commit()
        return self._db

    async def _get_field(self, account_id: str, field: str) -> Optional[str]:
        db = await self._ensure_db()
        async with db.execute(
            f"SELECT {field} FROM account_state WHERE account_id = ?",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else None

    async def _set_field(self, account_id: str, field: str, value: str) -> None:
        db = await self._ensure_db()
        await db.execute(
            f"INSERT INTO account_state (account_id, {field}) VALUES (?, ?) "
            f"ON CONFLICT(account_id) DO UPDATE SET {field} = excluded.{field}",
            (account_id, value),
        )
        await db.commit()

    async def load_token(self, account_id: str) -> Optional[str]:
        return await self._get_field(account_id, "token")

    async def save_token(self, account_id: str, token: str) -> None:
        await self._set_field(account_id, "token", token)

    async def load_cursor(self, account_id: str) -> Optional[str]:
        return await self._get_field(account_id, "cursor")

    async def save_cursor(self, account_id: str, cursor: str) -> None:
        await self._set_field(account_id, "cursor", cursor)

    async def load_meta(self, account_id: str) -> Optional[dict]:
        raw = await self._get_field(account_id, "meta")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def save_meta(self, account_id: str, meta: dict) -> None:
        await self._set_field(account_id, "meta", json.dumps(meta))

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
