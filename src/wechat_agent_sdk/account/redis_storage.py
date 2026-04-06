"""Redis-backed account storage."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .storage import AccountStorage

logger = logging.getLogger(__name__)


class RedisStorage(AccountStorage):
    """
    Redis-backed account state persistence.

    Requires ``redis`` package::

        pip install 'wechat-agent-sdk[redis]'

    Keys: ``{prefix}:{account_id}:token``, ``{prefix}:{account_id}:cursor``,
    ``{prefix}:{account_id}:meta``.
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379",
        prefix: str = "wechat-sdk",
        client: Any = None,
    ):
        self._url = url
        self._prefix = prefix
        self._client = client
        self._owned = client is None  # close only if we created it

    def _key(self, account_id: str, field: str) -> str:
        return f"{self._prefix}:{account_id}:{field}"

    async def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis
            except ImportError:
                raise ImportError(
                    "redis package required. Install: pip install 'wechat-agent-sdk[redis]'"
                )
            self._client = aioredis.from_url(self._url)
        return self._client

    async def load_token(self, account_id: str) -> Optional[str]:
        r = await self._ensure_client()
        val = await r.get(self._key(account_id, "token"))
        return val.decode() if val else None

    async def save_token(self, account_id: str, token: str) -> None:
        r = await self._ensure_client()
        if token:
            await r.set(self._key(account_id, "token"), token)
        else:
            await r.delete(self._key(account_id, "token"))

    async def load_cursor(self, account_id: str) -> Optional[str]:
        r = await self._ensure_client()
        val = await r.get(self._key(account_id, "cursor"))
        return val.decode() if val else None

    async def save_cursor(self, account_id: str, cursor: str) -> None:
        r = await self._ensure_client()
        await r.set(self._key(account_id, "cursor"), cursor)

    async def load_meta(self, account_id: str) -> Optional[dict]:
        r = await self._ensure_client()
        val = await r.get(self._key(account_id, "meta"))
        if val:
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def save_meta(self, account_id: str, meta: dict) -> None:
        r = await self._ensure_client()
        await r.set(self._key(account_id, "meta"), json.dumps(meta))

    async def close(self) -> None:
        if self._client and self._owned:
            await self._client.aclose()
            self._client = None
