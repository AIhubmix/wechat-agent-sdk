"""
最简 Echo 示例 — 回复用户发送的消息。

Usage:
    python examples/echo_bot.py
"""

import asyncio

from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot


class EchoAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=f"你说了: {request.text}")


async def main():
    bot = WeChatBot(agent=EchoAgent())
    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
