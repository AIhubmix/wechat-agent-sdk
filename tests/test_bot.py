"""Test WeChatBot lifecycle (integration-level with mocks)."""

import asyncio
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

    # Start bot in background, then stop it
    task = asyncio.create_task(bot.run())
    await asyncio.sleep(0.2)

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
