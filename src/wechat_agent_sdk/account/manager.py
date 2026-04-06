"""Account lifecycle management — the WeChatBot orchestrator."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx

from ..agent import Agent
from ..middleware import Context, Middleware, MiddlewareChain, ErrorHandler, make_error_middleware
from ..transport import WeChatTransport, ParsedMessage, LoginRequiredError
from ..types import ChatRequest, ChatResponse, MediaResponseInfo
from .storage import AccountStorage

logger = logging.getLogger(__name__)


def _to_chat_request(msg: ParsedMessage) -> ChatRequest:
    """Convert transport ParsedMessage to agent-layer ChatRequest."""
    return ChatRequest(
        conversation_id=msg.conversation_id,
        text=msg.text,
        media=msg.media[0] if msg.media else None,
        message_id=msg.message_id,
        group_id=msg.group_id,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        is_at_bot=msg.is_at_bot,
        raw=msg.raw,
    )


class WeChatBot:
    """
    Orchestrates a single WeChat account: login, monitor, graceful shutdown.

    Internally uses ``WeChatTransport`` for all I/O.

    Usage::

        bot = WeChatBot(agent=my_agent)
        await bot.run()  # blocks until stopped
    """

    def __init__(
        self,
        agent: Agent,
        account_id: str = "default",
        storage: Optional[AccountStorage] = None,
        token: str = "",
        api_base_url: str = "",
        max_concurrent: int = 10,
    ):
        self._agent = agent
        self._transport = WeChatTransport(
            account_id=account_id,
            storage=storage,
            token=token,
            api_base_url=api_base_url,
        )
        self._middleware = MiddlewareChain()
        # Default error middleware (sends error message to user)
        self._middleware.use(make_error_middleware(notify_user=True))
        self._running = False
        self._max_concurrent = max_concurrent
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def account_id(self) -> str:
        return self._transport.account_id

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def transport(self) -> WeChatTransport:
        """Expose the underlying transport for mixed-mode usage."""
        return self._transport

    def use(self, mw: Middleware) -> None:
        """Add a middleware to the processing chain."""
        self._middleware.use(mw)

    @classmethod
    def builder(cls) -> "WeChatBotBuilder":
        """Create a fluent builder for WeChatBot configuration."""
        return WeChatBotBuilder()

    async def login(self, log: callable = print) -> str:
        """Login via QR code (interactive terminal)."""
        return await self._transport.login_terminal(log=log)

    async def run(self, log: callable = print, auto_login: bool = True) -> None:
        """
        Start the bot and block until stopped.

        Automatically logs in if no token is available and ``auto_login``
        is True (default). Set ``auto_login=False`` for headless/web-login
        scenarios where the platform handles login separately.
        """
        if self._transport.needs_login:
            if auto_login:
                await self.login(log=log)
            else:
                raise LoginRequiredError(
                    "No token. Call request_login() + check_login() first."
                )

        await self._transport.connect()
        await self._agent.on_start()
        self._running = True
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        # Inject message_sender for streaming agents (e.g. AcpAgent)
        self._setup_message_sender()

        log(f"[weixin] Bot 已启动 (account={self._transport.account_id})")

        try:
            async for raw_msg in self._transport.messages():
                if not self._running:
                    break
                # Dispatch concurrently, bounded by semaphore
                task = asyncio.create_task(self._handle_message_guarded(raw_msg))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except asyncio.CancelledError:
            pass
        finally:
            # Wait for in-flight message handlers to finish
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            await self.stop()

    async def _handle_message_guarded(self, raw_msg: dict) -> None:
        """Acquire semaphore, then handle message."""
        async with self._semaphore:
            await self._handle_message(raw_msg)

    async def _handle_message(self, raw_msg: dict) -> None:
        """Parse, dispatch through middleware, send response."""
        parsed = self._transport.parse(raw_msg)
        if parsed is None:
            return

        request = _to_chat_request(parsed)
        ctx = Context(
            request=request,
            account_id=self._transport.account_id,
            context_token=parsed.context_token,
        )

        logger.info(f"Inbound: from={parsed.conversation_id} text={request.text[:50]!r}")

        # Track active conversation for intermediate message sender
        self._active_chat_id = parsed.conversation_id
        self._active_context_token = parsed.context_token

        # Typing indicator start
        await self._transport.send_typing(
            parsed.conversation_id, start=True, context_token=parsed.context_token
        )

        try:
            async def _core(ctx: Context) -> None:
                ctx.response = await self._agent.chat(ctx.request)

            await self._middleware.execute(ctx, _core)

            # Send response
            response = ctx.response or ChatResponse()
            if response.text:
                await self._transport.send_text(
                    parsed.conversation_id, response.text, parsed.context_token
                )
            if response.media:
                file_data = await self._read_media_response(response.media)
                await self._transport.send_media(
                    parsed.conversation_id,
                    file_data,
                    response.media.type,
                    response.media.file_name or "",
                    parsed.context_token,
                )
        finally:
            # Typing indicator stop
            await self._transport.send_typing(
                parsed.conversation_id, start=False, context_token=parsed.context_token
            )

    async def stop(self) -> None:
        """Graceful shutdown."""
        if not self._running:
            return
        logger.info(f"[weixin] Stopping bot (account={self._transport.account_id})")
        self._running = False
        await self._agent.on_stop()
        await self._transport.disconnect()
        logger.info(f"[weixin] Bot stopped (account={self._transport.account_id})")

    def _setup_message_sender(self) -> None:
        """Give the agent the ability to send intermediate messages."""
        if not hasattr(self._agent, "set_message_sender"):
            return

        async def _send_intermediate(text: str) -> None:
            # Use the most recently handled conversation
            chat_id = getattr(self, "_active_chat_id", None)
            ctx_token = getattr(self, "_active_context_token", "")
            if not chat_id or not text:
                return
            await self._transport.send_text(chat_id, text, ctx_token)

        self._agent.set_message_sender(_send_intermediate)

    async def _read_media_response(self, media: MediaResponseInfo) -> bytes:
        """Read media bytes from a ChatResponse media field."""
        if media.url.startswith(("http://", "https://")):
            async with httpx.AsyncClient() as http:
                resp = await http.get(media.url, timeout=60.0)
                resp.raise_for_status()
                return resp.content
        else:
            return await asyncio.to_thread(Path(media.url).read_bytes)


class WeChatBotBuilder:
    """Fluent builder for WeChatBot (avoids constructor explosion)."""

    def __init__(self) -> None:
        self._agent: Optional[Agent] = None
        self._account_id = "default"
        self._storage: Optional[AccountStorage] = None
        self._token = ""
        self._api_base_url = ""
        self._middlewares: list[Middleware] = []
        self._error_handler: Optional[ErrorHandler] = None
        self._auto_login = True
        self._max_concurrent = 10

    def agent(self, agent: Agent) -> "WeChatBotBuilder":
        self._agent = agent
        return self

    def account_id(self, account_id: str) -> "WeChatBotBuilder":
        self._account_id = account_id
        return self

    def storage(self, storage: AccountStorage) -> "WeChatBotBuilder":
        self._storage = storage
        return self

    def token(self, token: str) -> "WeChatBotBuilder":
        self._token = token
        return self

    def api_base_url(self, url: str) -> "WeChatBotBuilder":
        self._api_base_url = url
        return self

    def middleware(self, mw: Middleware) -> "WeChatBotBuilder":
        self._middlewares.append(mw)
        return self

    def on_error(self, handler: ErrorHandler) -> "WeChatBotBuilder":
        self._error_handler = handler
        return self

    def max_concurrent(self, n: int) -> "WeChatBotBuilder":
        """Max concurrent message handlers (default 10)."""
        self._max_concurrent = n
        return self

    def build(self) -> WeChatBot:
        if not self._agent:
            raise ValueError("agent is required — call .agent(my_agent) before .build()")
        bot = WeChatBot(
            agent=self._agent,
            account_id=self._account_id,
            storage=self._storage,
            token=self._token,
            api_base_url=self._api_base_url,
            max_concurrent=self._max_concurrent,
        )
        # Replace default error middleware if custom handler provided
        if self._error_handler:
            bot._middleware = MiddlewareChain()
            bot._middleware.use(make_error_middleware(handler=self._error_handler))
        for mw in self._middlewares:
            bot.use(mw)
        return bot
