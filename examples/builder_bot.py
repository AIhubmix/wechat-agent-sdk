"""
Builder 模式 + 中间件示例。

演示：
- WeChatBot.builder() 流式构建
- 自定义中间件（日志、限流）
- 自定义错误处理

Usage:
    python examples/builder_bot.py
"""

import asyncio
import time

from wechat_agent_sdk import (
    Agent,
    ChatRequest,
    ChatResponse,
    Context,
    WeChatBot,
    make_error_middleware,
)


class SmartAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        if "error" in request.text:
            raise ValueError("Simulated error for testing")
        return ChatResponse(text=f"Reply: {request.text}")


# ── Middleware examples ──

async def logging_middleware(ctx: Context, next_fn):
    """Log inbound and outbound messages."""
    print(f"[LOG] ← {ctx.request.conversation_id}: {ctx.request.text[:50]}")
    start = time.time()
    await next_fn()
    elapsed = time.time() - start
    reply = ctx.response.text[:50] if ctx.response and ctx.response.text else "None"
    print(f"[LOG] → {reply} ({elapsed:.2f}s)")


_last_message_time: dict[str, float] = {}

async def rate_limit_middleware(ctx: Context, next_fn):
    """Simple per-user rate limiter (1 message per second)."""
    user = ctx.request.conversation_id
    now = time.time()
    last = _last_message_time.get(user, 0)
    if now - last < 1.0:
        ctx.response = ChatResponse(text="Too fast, please wait a moment.")
        return  # short-circuit
    _last_message_time[user] = now
    await next_fn()


async def custom_error_handler(ctx: Context, error: Exception):
    """Custom error handler: log and return friendly message."""
    print(f"[ERROR] {error}")
    return ChatResponse(text=f"Oops: {error}")


# ── Main ──

async def main():
    bot = (
        WeChatBot.builder()
        .agent(SmartAgent())
        .on_error(custom_error_handler)
        .middleware(logging_middleware)
        .middleware(rate_limit_middleware)
        .build()
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
