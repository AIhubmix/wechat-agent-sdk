"""ACP (Agent Client Protocol) adapter — bridges ACP agents to WeChat."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from ..agent import Agent
from ..types import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

# Default permission mode for known ACP agents (e.g. claude-agent-acp).
# "bypassPermissions" skips interactive permission prompts that would block
# in a non-terminal environment like WeChat.
DEFAULT_PERMISSION_MODE = "bypassPermissions"


class AcpAgent(Agent):
    """
    Agent adapter that spawns an ACP-compatible subprocess
    (e.g. claude-agent-acp, codex-acp, kimi acp) and bridges it to WeChat.

    Supports streaming: when a ``message_sender`` callback is injected
    (via ``set_message_sender``), accumulated text is flushed to WeChat
    before each tool call starts, so the user sees incremental output
    instead of waiting for the entire response.

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
        permission_mode: Optional[str] = DEFAULT_PERMISSION_MODE,
    ):
        """
        Args:
            command: ACP agent launch command (e.g. "claude-agent-acp").
            args: Extra CLI arguments for the agent command.
            cwd: Working directory for the agent subprocess.
            env: Additional environment variables merged into the subprocess env.
            auto_approve: Auto-approve ACP permission requests (selects the
                first option). This handles ACP-protocol-level permissions.
            permission_mode: Controls the agent's **internal** permission
                behaviour via the ``ACP_PERMISSION_MODE`` environment variable.
                This is separate from ``auto_approve`` — many ACP agents
                (e.g. claude-agent-acp) check this env var to decide whether
                to prompt for confirmation in non-interactive environments.

                Supported values (for claude-agent-acp / claude-code-acp):

                - ``"bypassPermissions"`` — skip all permission prompts
                  (default; recommended for WeChat where no terminal is
                  available to confirm interactively).
                - ``"acceptEdits"`` — auto-approve file edits only; other
                  operations still require confirmation.
                - ``"default"`` — ask for confirmation on everything (will
                  likely cause the agent to reply "I don't have permission"
                  in non-interactive environments).
                - ``None`` — do not set the env var; let the agent decide.
        """
        self._command = command
        self._args = args or []
        self._cwd = cwd or os.getcwd()
        self._env = env
        self._auto_approve = auto_approve
        self._permission_mode = permission_mode

        self._conn = None  # ClientSideConnection
        self._process = None
        self._sessions: dict[str, str] = {}  # conversation_id -> acp session_id
        self._ctx = None  # async context manager

        # Accumulated text per session during a prompt call
        self._response_texts: dict[str, list[str]] = {}

        # Lock per session to serialise flush operations
        self._flush_locks: dict[str, asyncio.Lock] = {}

        # The conversation_id currently being processed (for flush routing)
        self._active_conversations: dict[str, str] = {}  # session_id -> conversation_id

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

                tool_name = getattr(tool_call, "name", None) or getattr(tool_call, "tool", "?")
                logger.info(
                    f"[acp] permission request: tool={tool_name} "
                    f"options={[o.id for o in options] if options else []}"
                )

                if agent_ref._auto_approve and options:
                    logger.info(f"[acp] auto-approved: {options[0].id}")
                    return RequestPermissionResponse(
                        outcome=PermissionOutcome(
                            outcome="selected",
                            optionId=options[0].id,
                        ),
                    )
                # Deny if no options or auto_approve is off
                logger.warning("[acp] permission denied (no options or auto_approve=False)")
                return RequestPermissionResponse(
                    outcome=PermissionOutcome(outcome="denied"),
                )

        client = WeChatClient()

        # Build subprocess environment with permission mode
        spawn_env = {**os.environ, **(self._env or {})}
        if self._permission_mode:
            spawn_env.setdefault("ACP_PERMISSION_MODE", self._permission_mode)

        # Spawn agent subprocess
        self._ctx = spawn_agent_process(
            client,
            self._command,
            *self._args,
            env=spawn_env,
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
        logger.info(
            f"[acp] Connection initialized "
            f"(command={self._command}, permission_mode={self._permission_mode})"
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a message to the ACP agent and collect the response."""
        if not self._conn:
            raise RuntimeError("ACP agent not started. Call on_start() first.")

        from acp import text_block

        # Get or create ACP session for this conversation
        session_id = await self._get_or_create_session(request.conversation_id)

        # Map session -> conversation for flush routing
        self._active_conversations[session_id] = request.conversation_id

        # Prepare prompt content
        blocks = []
        if request.text:
            blocks.append(text_block(request.text))

        if not blocks:
            return ChatResponse(text="")

        # Set up response collector
        self._response_texts[session_id] = []
        self._flush_locks.setdefault(session_id, asyncio.Lock())

        preview = request.text[:50] if request.text else "[no text]"
        logger.info(f"[acp] prompt: {preview!r} (session={session_id})")

        # Send prompt and wait for completion
        await self._conn.prompt(prompt=blocks, session_id=session_id)

        # Flush any remaining accumulated text
        remaining = await self._flush_text(session_id)

        # Clean up
        self._response_texts.pop(session_id, None)
        self._active_conversations.pop(session_id, None)

        logger.info(f"[acp] response (final): {(remaining or '')[:80]!r}")
        return ChatResponse(text=remaining or None)

    async def on_stop(self) -> None:
        """Kill the ACP agent subprocess."""
        self._sessions.clear()
        self._response_texts.clear()
        self._active_conversations.clear()
        self._flush_locks.clear()

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
            title = getattr(update, "title", "") or ""
            logger.info(f"[acp] tool_call_start: {title}")
            # Flush accumulated text before tool call, then send a status hint
            self._schedule_flush(session_id, tool_title=title)

        elif update_type == "ToolCallProgress":
            title = getattr(update, "title", "") or getattr(update, "toolCallId", "")
            status = getattr(update, "status", "")
            if status:
                logger.debug(f"[acp] tool_progress: {title} -> {status}")

        elif update_type == "AgentThoughtChunk":
            if hasattr(update, "content") and hasattr(update.content, "text"):
                logger.debug(f"[acp] thinking: {update.content.text[:100]}")

    def _schedule_flush(self, session_id: str, tool_title: str = "") -> None:
        """Schedule an async flush of accumulated text (called from sync callback)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._do_flush(session_id, tool_title))
        except RuntimeError:
            pass  # No running loop — skip

    async def _do_flush(self, session_id: str, tool_title: str = "") -> None:
        """Flush accumulated text to WeChat via message_sender, then send tool status."""
        text = await self._flush_text(session_id)

        if not self._message_sender:
            return

        # Send accumulated text if any
        if text:
            try:
                await self._message_sender(text)
            except Exception as e:
                logger.error(f"[acp] flush send error: {e}")

        # Send tool call status hint
        if tool_title:
            try:
                await self._message_sender(f"⏳ {tool_title}...")
            except Exception as e:
                logger.error(f"[acp] tool status send error: {e}")

    async def _flush_text(self, session_id: str) -> str:
        """Drain and return accumulated text for a session (thread-safe)."""
        lock = self._flush_locks.get(session_id)
        if not lock:
            return ""

        async with lock:
            texts = self._response_texts.get(session_id, [])
            if not texts:
                return ""
            result = "".join(texts)
            texts.clear()
            return result
