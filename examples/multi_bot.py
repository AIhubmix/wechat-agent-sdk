"""
多账号管理示例。

WeChatBotManager 管理多个 bot 实例，支持独立启停和自动重启。

Usage:
    python examples/multi_bot.py
"""

import asyncio

from wechat_agent_sdk import (
    Agent,
    ChatRequest,
    ChatResponse,
    WeChatBotManager,
)


class TaggedAgent(Agent):
    """An agent that prefixes replies with its tag."""

    def __init__(self, tag: str):
        self._tag = tag

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=f"[{self._tag}] {request.text}")


async def main():
    manager = WeChatBotManager(auto_restart=True, max_restart_attempts=3)

    # Register multiple bots
    manager.add_bot("bot_alice", agent=TaggedAgent("Alice"))
    manager.add_bot("bot_bob", agent=TaggedAgent("Bob"))

    print(f"Registered {manager.bot_count} bots")
    print(f"Status: {manager.get_status()}")

    # Each bot needs to login separately
    # In a real scenario, you'd call bot.login() or use the web login API

    try:
        await manager.start_all()
    except KeyboardInterrupt:
        pass
    finally:
        await manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
