"""Account lifecycle management — the WeChatBot orchestrator."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..agent import Agent
from ..api.auth import login_with_qrcode
from ..api.client import DEFAULT_API_BASE, ILinkBotClient
from ..messaging.monitor import MessageMonitor
from .storage import AccountStorage, JsonFileStorage

logger = logging.getLogger(__name__)


class WeChatBot:
    """
    Orchestrates a single WeChat account: login, monitor, graceful shutdown.

    Usage::

        bot = WeChatBot(agent=my_agent)
        await bot.login()
        await bot.run()  # blocks until stopped
    """

    def __init__(
        self,
        agent: Agent,
        account_id: str = "default",
        storage: Optional[AccountStorage] = None,
        token: str = "",
        api_base_url: str = "",
    ):
        self._agent = agent
        self._account_id = account_id
        self._storage = storage or JsonFileStorage()

        self._client = ILinkBotClient(
            token=token,
            base_url=api_base_url or DEFAULT_API_BASE,
        )
        self._monitor = MessageMonitor(self._client, agent)
        self._log = logger.info

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def is_running(self) -> bool:
        return self._monitor._running

    async def login(self, log: callable = print) -> str:
        """
        Login via QR code (interactive terminal).

        If a token is already stored, uses it directly.
        Returns the token.
        """
        # Try to load existing token
        stored_token = await self._storage.load_token(self._account_id)
        if stored_token:
            self._client.token = stored_token
            log(f"[weixin] 使用已保存的 token (account={self._account_id})")
            return stored_token

        # Interactive QR login
        token = await login_with_qrcode(self._client, log=log)

        # Persist
        await self._storage.save_token(self._account_id, token)
        return token

    async def run(self, log: callable = print) -> None:
        """
        Start the bot and block until stopped.

        Automatically logs in if no token is available.
        """
        if not self._client.token:
            await self.login(log=log)

        # Load cursor for resume
        cursor = await self._storage.load_cursor(self._account_id)
        if cursor:
            self._monitor.cursor = cursor
            log(f"[weixin] 从上次位置继续 (cursor={len(cursor)} bytes)")

        # Agent lifecycle
        await self._agent.on_start()

        log(f"[weixin] Bot 已启动 (account={self._account_id})")

        # Start monitor
        await self._monitor.start()

        # Periodically persist cursor
        try:
            while self._monitor._running:
                await asyncio.sleep(5.0)
                if self._monitor.cursor:
                    await self._storage.save_cursor(self._account_id, self._monitor.cursor)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info(f"[weixin] Stopping bot (account={self._account_id})")

        await self._monitor.stop()
        await self._agent.on_stop()

        # Persist final cursor
        if self._monitor.cursor:
            await self._storage.save_cursor(self._account_id, self._monitor.cursor)

        await self._client.close()
        logger.info(f"[weixin] Bot stopped (account={self._account_id})")
