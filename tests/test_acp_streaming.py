"""Tests for AcpAgent streaming flush logic (no acp package dependency)."""

import asyncio
import pytest
from types import SimpleNamespace

from wechat_agent_sdk.acp.adapter import AcpAgent


def _make_agent() -> AcpAgent:
    """Create an AcpAgent without spawning a real subprocess."""
    agent = AcpAgent(command="fake-acp")
    # Pre-populate internal state as if on_start() + _get_or_create_session() ran
    agent._sessions = {"user1": "session-abc"}
    agent._response_texts = {"session-abc": []}
    agent._flush_locks = {"session-abc": asyncio.Lock()}
    agent._active_conversations = {"session-abc": "user1"}
    return agent


class AgentMessageChunk:
    def __init__(self, text: str):
        self.content = SimpleNamespace(text=text)


class ToolCallStart:
    def __init__(self, title: str):
        self.title = title


def _msg_chunk(text: str):
    return AgentMessageChunk(text)


def _tool_start(title: str):
    return ToolCallStart(title)


# -------------------------------------------------------------------
# Test: text chunks accumulate correctly
# -------------------------------------------------------------------
def test_text_accumulation():
    agent = _make_agent()
    agent._handle_session_update("session-abc", _msg_chunk("Hello "))
    agent._handle_session_update("session-abc", _msg_chunk("world"))
    assert agent._response_texts["session-abc"] == ["Hello ", "world"]


# -------------------------------------------------------------------
# Test: _flush_text drains the buffer and returns joined text
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flush_text_drains_buffer():
    agent = _make_agent()
    agent._response_texts["session-abc"] = ["Hello ", "world"]

    result = await agent._flush_text("session-abc")
    assert result == "Hello world"
    assert agent._response_texts["session-abc"] == []  # buffer cleared


@pytest.mark.asyncio
async def test_flush_text_empty_returns_empty():
    agent = _make_agent()
    result = await agent._flush_text("session-abc")
    assert result == ""


# -------------------------------------------------------------------
# Test: ToolCallStart triggers flush via _schedule_flush
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_call_start_flushes_text():
    agent = _make_agent()
    sent_messages: list[str] = []

    async def fake_sender(text: str) -> None:
        sent_messages.append(text)

    agent.set_message_sender(fake_sender)

    # Simulate: agent sends text, then a tool call starts
    agent._handle_session_update("session-abc", _msg_chunk("I'll read the file. "))
    agent._handle_session_update("session-abc", _msg_chunk("Let me check."))
    agent._handle_session_update("session-abc", _tool_start("Read file"))

    # Give the scheduled task a chance to run
    await asyncio.sleep(0.05)

    # The accumulated text should have been flushed
    assert "I'll read the file. Let me check." in sent_messages
    # Tool status hint should also be sent
    assert "⏳ Read file..." in sent_messages
    # Buffer should be empty
    assert agent._response_texts["session-abc"] == []


# -------------------------------------------------------------------
# Test: multiple tool calls flush incrementally
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multiple_tool_calls_flush_incrementally():
    agent = _make_agent()
    sent_messages: list[str] = []

    async def fake_sender(text: str) -> None:
        sent_messages.append(text)

    agent.set_message_sender(fake_sender)

    # First chunk + tool call
    agent._handle_session_update("session-abc", _msg_chunk("Part 1. "))
    agent._handle_session_update("session-abc", _tool_start("Read file"))
    await asyncio.sleep(0.05)

    # Second chunk + tool call
    agent._handle_session_update("session-abc", _msg_chunk("Part 2. "))
    agent._handle_session_update("session-abc", _tool_start("Run command"))
    await asyncio.sleep(0.05)

    # Both parts should have been flushed separately
    assert "Part 1. " in sent_messages
    assert "Part 2. " in sent_messages
    assert "⏳ Read file..." in sent_messages
    assert "⏳ Run command..." in sent_messages


# -------------------------------------------------------------------
# Test: no sender set — flush does nothing, no error
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flush_without_sender_no_error():
    agent = _make_agent()
    # No set_message_sender called
    agent._handle_session_update("session-abc", _msg_chunk("text"))
    agent._handle_session_update("session-abc", _tool_start("Read"))
    await asyncio.sleep(0.05)
    # Text should still be cleared from buffer by _flush_text in _do_flush
    # (even though nothing was sent)
    assert agent._response_texts["session-abc"] == []


# -------------------------------------------------------------------
# Test: permission_mode sets env correctly
# -------------------------------------------------------------------
def test_permission_mode_default():
    agent = AcpAgent(command="test")
    assert agent._permission_mode == "bypassPermissions"


def test_permission_mode_custom():
    agent = AcpAgent(command="test", permission_mode="acceptEdits")
    assert agent._permission_mode == "acceptEdits"


def test_permission_mode_none():
    agent = AcpAgent(command="test", permission_mode=None)
    assert agent._permission_mode is None
