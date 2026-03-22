"""
OpenAI Agent 示例 — 使用 OpenAI API 回复消息，支持多轮对话。

Usage:
    OPENAI_API_KEY=sk-xxx python examples/openai_bot.py

Environment variables:
    OPENAI_API_KEY  - Required. Your OpenAI API key.
    OPENAI_BASE_URL - Optional. Custom API base URL (for compatible services).
    OPENAI_MODEL    - Optional. Model name (default: gpt-4o).
    SYSTEM_PROMPT   - Optional. System prompt.
"""

import asyncio
import os

from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot


class OpenAIAgent(Agent):
    def __init__(self):
        self._conversations: dict[str, list[dict]] = {}
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._system_prompt = os.environ.get("SYSTEM_PROMPT", "你是一个友好的AI助手。")
        self._client = None

    async def on_start(self) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package is required. Install with: pip install 'wechat-agent-sdk[openai]'"
            )

        self._client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        history = self._conversations.setdefault(request.conversation_id, [])
        history.append({"role": "user", "content": request.text})

        messages = [{"role": "system", "content": self._system_prompt}] + history[-20:]

        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )

        reply = resp.choices[0].message.content or ""
        history.append({"role": "assistant", "content": reply})

        return ChatResponse(text=reply)


async def main():
    bot = WeChatBot(agent=OpenAIAgent())
    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
