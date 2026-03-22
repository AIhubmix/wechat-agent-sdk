"""ACP (Agent Client Protocol) adapter — bridges ACP agents to WeChat."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from ..agent import Agent
from ..types import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


class AcpAgent(Agent):
    """
    Agent adapter that spawns an ACP-compatible subprocess
    (e.g. claude-agent-acp, codex-acp, kimi acp) and bridges it to WeChat.

    Usage::

        agent = AcpAgent(command="claude-agent-acp")
        bot = WeChatBot(agent=agent)
        await bot.run()
    """

    def __init__(
        self,
        command: str,
        args: Optional[list[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        auto_approve: bool = True,
    ):
        self._command = command
        self._args = args or []
        self._cwd = cwd or os.getcwd()
        self._env = env
        self._auto_approve = auto_approve

        self._conn = None  # ClientSideConnection
        self._process = None
        self._sessions: dict[str, str] = {}  # conversation_id -> acp session_id
        self._ctx = None  # async context manager

        # Accumulated text per session during a prompt call
        self._response_texts: dict[str, list[str]] = {}

    async def on_start(self) -> None:
        """Spawn the ACP agent subprocess and initialize the connection."""
        try:
            from acp import (
                Client,
                PROTOCOL_VERSION,
                spawn_agent_process,
            )
            from acp.schema import Implementation, ClientCapabilities
        except ImportError:
            raise ImportError(
                "agent-client-protocol package is required for ACP support. "
                "Install it with: pip install 'wechat-agent-sdk[acp]'"
            )

        # Build the Client (handles sessionUpdate and requestPermission callbacks)
        agent_ref = self  # capture for closures

        class WeChatClient(Client):
            async def session_update(self, session_id, update, **kwargs):
                agent_ref._handle_session_update(session_id, update)

            async def request_permission(self, options, session_id, tool_call, **kwargs):
                from acp.schema import RequestPermissionResponse, PermissionOutcome

                if agent_ref._auto_approve and options:
                    return RequestPermissionResponse(
                        outcome=PermissionOutcome(
                            outcome="selected",
                            optionId=options[0].id,
                        ),
                    )
                # Deny if no options or auto_approve is off
                return RequestPermissionResponse(
                    outcome=PermissionOutcome(outcome="denied"),
                )

        client = WeChatClient()

        # Spawn agent subprocess
        self._ctx = spawn_agent_process(
            client,
            self._command,
            *self._args,
            env={**os.environ, **(self._env or {})},
            cwd=self._cwd,
        )
        self._conn, self._process = await self._ctx.__aenter__()

        # Initialize the ACP handshake
        await self._conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_info=Implementation(
                name="wechat-agent-sdk",
                version="0.1.0",
            ),
            client_capabilities=ClientCapabilities(),
        )
        logger.info(f"[acp] Connection initialized (command={self._command})")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a message to the ACP agent and collect the response."""
        if not self._conn:
            raise RuntimeError("ACP agent not started. Call on_start() first.")

        from acp import text_block

        # Get or create ACP session for this conversation
        session_id = await self._get_or_create_session(request.conversation_id)

        # Prepare prompt content
        blocks = []
        if request.text:
            blocks.append(text_block(request.text))

        if not blocks:
            return ChatResponse(text="")

        # Set up response collector
        self._response_texts[session_id] = []

        preview = request.text[:50] if request.text else "[no text]"
        logger.info(f"[acp] prompt: {preview!r} (session={session_id})")

        # Send prompt and wait for completion
        await self._conn.prompt(prompt=blocks, session_id=session_id)

        # Collect accumulated text
        texts = self._response_texts.pop(session_id, [])
        response_text = "".join(texts)

        logger.info(f"[acp] response: {response_text[:80]!r}")
        return ChatResponse(text=response_text or None)

    async def on_stop(self) -> None:
        """Kill the ACP agent subprocess."""
        self._sessions.clear()
        self._response_texts.clear()

        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._ctx = None
            self._conn = None
            self._process = None

        logger.info("[acp] Agent stopped")

    async def _get_or_create_session(self, conversation_id: str) -> str:
        """Get existing or create new ACP session for a conversation."""
        if conversation_id in self._sessions:
            return self._sessions[conversation_id]

        logger.info(f"[acp] Creating new session for conversation={conversation_id}")
        resp = await self._conn.new_session(cwd=self._cwd)
        session_id = resp.session_id
        self._sessions[conversation_id] = session_id
        logger.info(f"[acp] Session created: {session_id}")
        return session_id

    def _handle_session_update(self, session_id: str, update) -> None:
        """Process ACP sessionUpdate notifications."""
        update_type = type(update).__name__

        if update_type == "AgentMessageChunk":
            # Accumulate text from agent message chunks
            if hasattr(update, "content") and hasattr(update.content, "text"):
                text = update.content.text
                if session_id in self._response_texts:
                    self._response_texts[session_id].append(text)

        elif update_type == "ToolCallStart":
            title = getattr(update, "title", "")
            logger.debug(f"[acp] tool_call: {title}")

        elif update_type == "ToolCallProgress":
            title = getattr(update, "title", "") or getattr(update, "toolCallId", "")
            status = getattr(update, "status", "")
            if status:
                logger.debug(f"[acp] tool_progress: {title} -> {status}")

        elif update_type == "AgentThoughtChunk":
            if hasattr(update, "content") and hasattr(update.content, "text"):
                logger.debug(f"[acp] thinking: {update.content.text[:100]}")
