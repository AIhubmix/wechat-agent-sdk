"""Test WeChatBot lifecycle (integration-level with mocks)."""

import asyncio
from unittest.mock import AsyncMock, patch
import pytest

from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot
from wechat_agent_sdk.account.storage import JsonFileStorage


class SimpleAgent(Agent):
    def __init__(self):
        self.started = False
        self.stopped = False

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text="reply")

    async def on_start(self):
        self.started = True

    async def on_stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_bot_login_with_existing_token(tmp_path):
    """Bot should skip QR login if token is already stored."""
    storage = JsonFileStorage(state_dir=tmp_path)
    await storage.save_token("default", "existing_token")

    agent = SimpleAgent()
    bot = WeChatBot(agent=agent, storage=storage)

    token = await bot.login()
    assert token == "existing_token"


@pytest.mark.asyncio
async def test_bot_lifecycle(tmp_path):
    """Bot should call agent on_start and on_stop."""
    storage = JsonFileStorage(state_dir=tmp_path)
    await storage.save_token("default", "test_token")

    agent = SimpleAgent()
    bot = WeChatBot(agent=agent, storage=storage)

    # Mock get_updates to return empty then allow cancel
    call_count = 0

    async def fake_get_updates(cursor=""):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            # Give time for stop() to run
            await asyncio.sleep(10)
        return [], cursor

    with patch.object(bot.transport.client, "get_updates", side_effect=fake_get_updates):
        task = asyncio.create_task(bot.run())
        await asyncio.sleep(0.1)

        assert agent.started is True

        await bot.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert agent.stopped is True


@pytest.mark.asyncio
async def test_bot_custom_account_id(tmp_path):
    storage = JsonFileStorage(state_dir=tmp_path)
    await storage.save_token("my_bot", "tok_123")

    agent = SimpleAgent()
    bot = WeChatBot(agent=agent, account_id="my_bot", storage=storage)

    assert bot.account_id == "my_bot"
    token = await bot.login()
    assert token == "tok_123"


@pytest.mark.asyncio
async def test_bot_transport_exposed(tmp_path):
    """Bot should expose its transport for mixed-mode usage."""
    storage = JsonFileStorage(state_dir=tmp_path)
    agent = SimpleAgent()
    bot = WeChatBot(agent=agent, storage=storage)

    assert bot.transport is not None
    assert bot.transport.account_id == "default"


@pytest.mark.asyncio
async def test_bot_builder():
    """Builder should create a configured bot."""
    agent = SimpleAgent()
    bot = (
        WeChatBot.builder()
        .agent(agent)
        .account_id("test_bot")
        .build()
    )
    assert bot.account_id == "test_bot"


@pytest.mark.asyncio
async def test_bot_builder_requires_agent():
    """Builder should raise if agent is not set."""
    with pytest.raises(ValueError, match="agent is required"):
        WeChatBot.builder().build()
