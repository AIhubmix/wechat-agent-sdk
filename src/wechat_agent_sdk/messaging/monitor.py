"""Long-poll message monitor."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Optional

from ..agent import Agent
from ..api.client import ILinkBotClient, SessionExpiredError
from ..types import ChatRequest, ChatResponse
from .process import parse_message
from .send import send_response

logger = logging.getLogger(__name__)

# Retry config
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY = 30.0
RETRY_DELAY = 2.0
SESSION_EXPIRED_COOLDOWN = 3600.0  # 1 hour


class MessageMonitor:
    """
    Long-poll loop: getUpdates -> parse -> agent.chat() -> send reply.

    Runs until stopped via ``stop()``.
    """

    def __init__(
        self,
        client: ILinkBotClient,
        agent: Agent,
        log: callable = print,
    ):
        self._client = client
        self._agent = agent
        self._log = log

        self._cursor: str = ""
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # context_token cache: chat_id -> latest context_token
        self._context_tokens: dict[str, str] = {}

        # typing ticket cache: chat_id -> (ticket, fetched_at)
        self._typing_tickets: dict[str, tuple[str, float]] = {}
        self._typing_ticket_ttl = 86400.0  # 24h

        # message dedup
        self._seen_ids: OrderedDict[str, None] = OrderedDict()

        # Inject streaming sender into agent (for AcpAgent incremental output)
        self._setup_message_sender()

    @property
    def cursor(self) -> str:
        return self._cursor

    @cursor.setter
    def cursor(self, value: str) -> None:
        self._cursor = value

    async def start(self) -> None:
        """Start the poll loop as a background task."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="wechat_poll")

    async def stop(self) -> None:
        """Stop the poll loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        """Main long-poll loop with exponential backoff."""
        consecutive_failures = 0

        while self._running:
            try:
                msgs, new_cursor = await self._client.get_updates(self._cursor)

                if new_cursor and new_cursor != self._cursor:
                    self._cursor = new_cursor

                consecutive_failures = 0

                for raw_msg in msgs:
                    await self._handle_message(raw_msg)

            except asyncio.CancelledError:
                break
            except SessionExpiredError:
                self._log(f"[weixin] 会话已过期，{SESSION_EXPIRED_COOLDOWN // 60:.0f} 分钟后重试...")
                logger.warning("Session expired, cooling down")
                await self._sleep(SESSION_EXPIRED_COOLDOWN)
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Poll error ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}")

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await self._sleep(BACKOFF_DELAY)
                else:
                    await self._sleep(RETRY_DELAY)

    async def _handle_message(self, raw_msg: dict) -> None:
        """Parse, dedup, dispatch a single message."""
        request = parse_message(raw_msg)
        if request is None:
            return

        # Dedup
        if request.message_id and self._is_duplicate(request.message_id):
            return

        # Cache context_token
        context_token = raw_msg.get("context_token", "")
        if context_token:
            self._context_tokens[request.conversation_id] = context_token

        chat_id = request.conversation_id
        logger.info(f"Inbound: from={chat_id} text={request.text[:50]!r}")

        # Set active chat for streaming sender
        self._active_chat_id = chat_id

        # Typing indicator (start)
        ticket = await self._get_typing_ticket(chat_id, context_token)
        if ticket:
            await self._client.send_typing(chat_id, ticket, start=True)

        try:
            response = await self._agent.chat(request)

            # Send response
            ctx = self._context_tokens.get(chat_id, "")
            await send_response(self._client, chat_id, response, ctx)

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            ctx = self._context_tokens.get(chat_id, "")
            await self._client.send_message(
                chat_id,
                f"⚠️ 处理消息失败: {e}",
                ctx,
            )
        finally:
            # Typing indicator (cancel)
            if ticket:
                await self._client.send_typing(chat_id, ticket, start=False)

    def _is_duplicate(self, message_id: str) -> bool:
        """Check and record message ID for dedup."""
        if message_id in self._seen_ids:
            return True
        self._seen_ids[message_id] = None
        while len(self._seen_ids) > 1000:
            self._seen_ids.popitem(last=False)
        return False

    async def _get_typing_ticket(self, chat_id: str, context_token: str = "") -> Optional[str]:
        """Get typing ticket for a user, with 24h cache."""
        cached = self._typing_tickets.get(chat_id)
        if cached:
            ticket, fetched_at = cached
            if time.time() - fetched_at < self._typing_ticket_ttl:
                return ticket

        try:
            data = await self._client.get_config(chat_id, context_token)
            ticket = data.get("typing_ticket") or data.get("typingTicket")
            if ticket:
                self._typing_tickets[chat_id] = (ticket, time.time())
                return ticket
        except Exception:
            pass

        return None

    def _setup_message_sender(self) -> None:
        """Give the agent the ability to send intermediate messages."""
        if not hasattr(self._agent, "set_message_sender"):
            return

        # _active_chat_id is set during _handle_message so the sender
        # knows which conversation to target.
        self._active_chat_id: Optional[str] = None

        async def _send_intermediate(text: str) -> None:
            chat_id = self._active_chat_id
            if not chat_id or not text:
                return
            ctx = self._context_tokens.get(chat_id, "")
            await send_response(self._client, chat_id, ChatResponse(text=text), ctx)

        self._agent.set_message_sender(_send_intermediate)

    async def _sleep(self, seconds: float) -> None:
        """Interruptible sleep."""
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise
