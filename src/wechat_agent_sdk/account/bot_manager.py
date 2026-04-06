"""Multi-account bot manager."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..agent import Agent
from ..transport import WeChatTransport
from .manager import WeChatBot
from .storage import AccountStorage, JsonFileStorage

logger = logging.getLogger(__name__)


class BotStatus(str, Enum):
    """Lifecycle status of a managed bot."""

    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class _BotEntry:
    account_id: str
    bot: WeChatBot
    status: BotStatus
    task: Optional[asyncio.Task] = None


class WeChatBotManager:
    """
    Manages multiple WeChatBot instances with lifecycle control.

    Usage::

        manager = WeChatBotManager(storage=RedisStorage())
        manager.add_bot("bot1", agent=MyAgent())
        manager.add_bot("bot2", agent=MyAgent())
        await manager.start_all()
        # ...
        await manager.stop_all()
    """

    def __init__(
        self,
        storage: Optional[AccountStorage] = None,
        api_base_url: str = "",
        auto_restart: bool = False,
        max_restart_attempts: int = 3,
    ):
        self._storage = storage or JsonFileStorage()
        self._api_base_url = api_base_url
        self._auto_restart = auto_restart
        self._max_restart_attempts = max_restart_attempts
        self._bots: dict[str, _BotEntry] = {}

    def add_bot(
        self,
        account_id: str,
        agent: Agent,
        **kwargs,
    ) -> WeChatBot:
        """Register a new bot. Does not start it."""
        if account_id in self._bots:
            raise ValueError(f"Bot already registered: {account_id}")

        bot = WeChatBot(
            agent=agent,
            account_id=account_id,
            storage=self._storage,
            api_base_url=self._api_base_url,
            **kwargs,
        )
        self._bots[account_id] = _BotEntry(
            account_id=account_id,
            bot=bot,
            status=BotStatus.CREATED,
        )
        return bot

    def remove_bot(self, account_id: str) -> None:
        """Remove a bot (must be stopped first)."""
        entry = self._bots.get(account_id)
        if not entry:
            raise KeyError(f"No bot with id: {account_id}")
        if entry.status == BotStatus.RUNNING:
            raise RuntimeError(f"Stop bot before removing: {account_id}")
        del self._bots[account_id]

    def get_bot(self, account_id: str) -> Optional[WeChatBot]:
        """Get a bot instance by account_id."""
        entry = self._bots.get(account_id)
        return entry.bot if entry else None

    def get_transport(self, account_id: str) -> Optional[WeChatTransport]:
        """Get the transport layer for a bot (for platform integration)."""
        bot = self.get_bot(account_id)
        return bot.transport if bot else None

    def get_status(self) -> dict[str, BotStatus]:
        """Return status of all bots."""
        return {aid: e.status for aid, e in self._bots.items()}

    @property
    def bot_count(self) -> int:
        return len(self._bots)

    async def start_bot(self, account_id: str) -> None:
        """Start a single bot in a background task."""
        entry = self._bots.get(account_id)
        if not entry:
            raise KeyError(f"No bot with id: {account_id}")

        entry.status = BotStatus.RUNNING

        if self._auto_restart:
            coro = self._run_with_restart(entry)
        else:
            coro = self._run_bot(entry)

        entry.task = asyncio.create_task(coro, name=f"bot_{account_id}")

    async def stop_bot(self, account_id: str) -> None:
        """Stop a single bot."""
        entry = self._bots.get(account_id)
        if not entry:
            return

        entry.status = BotStatus.STOPPED
        await entry.bot.stop()
        if entry.task and not entry.task.done():
            entry.task.cancel()
            try:
                await entry.task
            except asyncio.CancelledError:
                pass
        entry.task = None

    async def restart_bot(self, account_id: str) -> None:
        """Stop and re-start a bot."""
        await self.stop_bot(account_id)
        await self.start_bot(account_id)

    async def start_all(self) -> None:
        """Start all registered bots."""
        for account_id in self._bots:
            await self.start_bot(account_id)

    async def stop_all(self) -> None:
        """Stop all running bots."""
        for account_id in list(self._bots):
            await self.stop_bot(account_id)

    async def _run_bot(self, entry: _BotEntry) -> None:
        try:
            await entry.bot.run()
        except Exception as e:
            entry.status = BotStatus.ERROR
            logger.error(f"Bot {entry.account_id} crashed: {e}", exc_info=True)
        finally:
            if entry.status == BotStatus.RUNNING:
                entry.status = BotStatus.STOPPED

    async def _run_with_restart(self, entry: _BotEntry) -> None:
        """Run bot with exponential backoff restart."""
        attempts = 0
        while attempts < self._max_restart_attempts:
            try:
                await entry.bot.run()
                break  # clean exit
            except asyncio.CancelledError:
                break
            except Exception as e:
                attempts += 1
                entry.status = BotStatus.ERROR
                delay = min(2 ** attempts, 60)
                logger.error(
                    f"Bot {entry.account_id} crashed (attempt {attempts}/"
                    f"{self._max_restart_attempts}), restarting in {delay}s: {e}",
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                entry.status = BotStatus.RUNNING

        if entry.status != BotStatus.STOPPED:
            entry.status = BotStatus.ERROR
            logger.error(
                f"Bot {entry.account_id} exceeded max restart attempts"
            )
