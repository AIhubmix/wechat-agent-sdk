"""Pluggable account state persistence."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_STATE_DIR = Path.home() / ".wechat-agent-sdk"


class AccountStorage(ABC):
    """Abstract interface for persisting account state (token, cursor, metadata)."""

    @abstractmethod
    async def load_token(self, account_id: str) -> Optional[str]:
        ...

    @abstractmethod
    async def save_token(self, account_id: str, token: str) -> None:
        ...

    @abstractmethod
    async def load_cursor(self, account_id: str) -> Optional[str]:
        ...

    @abstractmethod
    async def save_cursor(self, account_id: str, cursor: str) -> None:
        ...

    async def load_meta(self, account_id: str) -> Optional[dict]:
        """Load account metadata (bot_id, base_url, etc.)."""
        return None

    async def save_meta(self, account_id: str, meta: dict) -> None:
        """Save account metadata."""

    async def close(self) -> None:
        """Close underlying connections (Redis, SQLite, etc.)."""


class JsonFileStorage(AccountStorage):
    """
    Simple JSON file persistence.

    Stores data in ``~/.wechat-agent-sdk/accounts.json``.
    """

    def __init__(self, state_dir: Path = DEFAULT_STATE_DIR):
        self._state_dir = state_dir
        self._file = state_dir / "accounts.json"
        self._data: Optional[dict] = None

    def _load(self) -> dict:
        if self._data is not None:
            return self._data

        if self._file.exists():
            try:
                self._data = json.loads(self._file.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

        return self._data

    def _save(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._data or {}, indent=2))

    def _get_account(self, account_id: str) -> dict:
        data = self._load()
        return data.setdefault(account_id, {})

    async def load_token(self, account_id: str) -> Optional[str]:
        return self._get_account(account_id).get("token") or None

    async def save_token(self, account_id: str, token: str) -> None:
        self._get_account(account_id)["token"] = token
        self._save()

    async def load_cursor(self, account_id: str) -> Optional[str]:
        return self._get_account(account_id).get("cursor") or None

    async def save_cursor(self, account_id: str, cursor: str) -> None:
        self._get_account(account_id)["cursor"] = cursor
        self._save()

    async def load_meta(self, account_id: str) -> Optional[dict]:
        return self._get_account(account_id).get("meta") or None

    async def save_meta(self, account_id: str, meta: dict) -> None:
        self._get_account(account_id)["meta"] = meta
        self._save()
