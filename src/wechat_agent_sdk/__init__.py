"""
wechat-agent-sdk — WeChat AI Agent bridge framework.

Provides a simple Agent interface to connect any AI backend to WeChat
via the iLink Bot API, with optional ACP (Agent Client Protocol) support.

Quick start::

    from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

    class EchoAgent(Agent):
        async def chat(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(text=f"Echo: {request.text}")

    bot = WeChatBot(agent=EchoAgent())
    await bot.run()
"""

from .agent import Agent
from .types import ChatRequest, ChatResponse, MediaInfo, MediaResponseInfo
from .account.manager import WeChatBot
from .account.storage import AccountStorage, JsonFileStorage

__all__ = [
    "Agent",
    "ChatRequest",
    "ChatResponse",
    "MediaInfo",
    "MediaResponseInfo",
    "WeChatBot",
    "AccountStorage",
    "JsonFileStorage",
]
