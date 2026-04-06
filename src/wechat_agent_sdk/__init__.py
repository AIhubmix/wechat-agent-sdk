"""
wechat-agent-sdk — WeChat AI Agent bridge framework.

Two-layer architecture:

**Transport layer** (platform integration)::

    from wechat_agent_sdk import WeChatTransport, ParsedMessage

    transport = WeChatTransport(account_id="bot_1")
    async for msg in transport.messages():
        parsed = transport.parse(msg)
        await transport.send_text(parsed.conversation_id, "reply")

**Bot layer** (standalone developers)::

    from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

    class EchoAgent(Agent):
        async def chat(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(text=f"Echo: {request.text}")

    bot = WeChatBot(agent=EchoAgent())
    await bot.run()
"""

# === Transport layer (platform integration) ===
from .transport import WeChatTransport, ParsedMessage, LoginRequiredError

# === Bot layer (standalone developers) ===
from .agent import Agent
from .types import ChatRequest, ChatResponse, MediaInfo, MediaResponseInfo
from .account.manager import WeChatBot, WeChatBotBuilder
from .middleware import Context, Middleware, MiddlewareChain, make_error_middleware
from .account.bot_manager import WeChatBotManager, BotStatus

# === Shared infrastructure ===
from .account.storage import AccountStorage, JsonFileStorage
from .api.auth import LoginSession, LoginResult, LoginStatus

__all__ = [
    # Transport
    "WeChatTransport",
    "ParsedMessage",
    "LoginRequiredError",
    # Bot
    "Agent",
    "ChatRequest",
    "ChatResponse",
    "MediaInfo",
    "MediaResponseInfo",
    "WeChatBot",
    "WeChatBotBuilder",
    "WeChatBotManager",
    "BotStatus",
    "Context",
    "Middleware",
    "MiddlewareChain",
    "make_error_middleware",
    # Shared
    "AccountStorage",
    "JsonFileStorage",
    "LoginSession",
    "LoginResult",
    "LoginStatus",
]
