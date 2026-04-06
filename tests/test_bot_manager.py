"""Test WeChatBotManager."""

import pytest

from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBotManager, BotStatus
from wechat_agent_sdk.account.storage import JsonFileStorage


class DummyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text="ok")


class TestBotManager:
    def test_add_and_get_bot(self):
        manager = WeChatBotManager()
        bot = manager.add_bot("bot1", agent=DummyAgent())
        assert bot is not None
        assert manager.get_bot("bot1") is bot
        assert manager.bot_count == 1

    def test_add_duplicate_raises(self):
        manager = WeChatBotManager()
        manager.add_bot("bot1", agent=DummyAgent())
        with pytest.raises(ValueError, match="already registered"):
            manager.add_bot("bot1", agent=DummyAgent())

    def test_remove_bot(self):
        manager = WeChatBotManager()
        manager.add_bot("bot1", agent=DummyAgent())
        manager.remove_bot("bot1")
        assert manager.get_bot("bot1") is None
        assert manager.bot_count == 0

    def test_remove_nonexistent_raises(self):
        manager = WeChatBotManager()
        with pytest.raises(KeyError):
            manager.remove_bot("nonexistent")

    def test_get_status(self):
        manager = WeChatBotManager()
        manager.add_bot("bot1", agent=DummyAgent())
        manager.add_bot("bot2", agent=DummyAgent())
        status = manager.get_status()
        assert status == {"bot1": BotStatus.CREATED, "bot2": BotStatus.CREATED}

    def test_get_transport(self):
        manager = WeChatBotManager()
        manager.add_bot("bot1", agent=DummyAgent())
        transport = manager.get_transport("bot1")
        assert transport is not None
        assert transport.account_id == "bot1"

    def test_get_transport_nonexistent(self):
        manager = WeChatBotManager()
        assert manager.get_transport("nope") is None
