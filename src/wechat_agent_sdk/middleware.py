"""Middleware chain for the Bot layer (onion model)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .types import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

# Middleware signature: async def mw(ctx, next) -> None
Middleware = Callable[["Context", Callable[[], Awaitable[None]]], Awaitable[None]]

# Error handler: async def handler(ctx, error) -> Optional[ChatResponse]
ErrorHandler = Callable[["Context", Exception], Awaitable[Optional[ChatResponse]]]


@dataclass
class Context:
    """Message context flowing through the middleware chain."""

    request: ChatRequest
    response: Optional[ChatResponse] = None
    account_id: str = ""
    context_token: str = ""
    extra: dict = field(default_factory=dict)


class MiddlewareChain:
    """
    Recursive onion middleware chain (Bot Framework style).

    Each middleware receives ``(ctx, next)`` and calls ``await next()``
    to proceed. Not calling ``next()`` short-circuits the chain.

    Usage::

        chain = MiddlewareChain()
        chain.use(logging_middleware)
        chain.use(rate_limit_middleware)
        await chain.execute(ctx, core_handler)
    """

    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []

    def use(self, mw: Middleware) -> None:
        """Append a middleware to the chain."""
        self._middlewares.append(mw)

    async def execute(
        self,
        context: Context,
        handler: Callable[[Context], Awaitable[None]],
    ) -> None:
        """Execute the chain, calling handler at the innermost layer."""

        async def _run(index: int) -> None:
            if index == len(self._middlewares):
                await handler(context)
                return
            await self._middlewares[index](context, lambda: _run(index + 1))

        await _run(0)


def make_error_middleware(
    handler: Optional[ErrorHandler] = None,
    notify_user: bool = True,
) -> Middleware:
    """
    Factory: create an error-handling middleware.

    If ``handler`` is provided, it is called first. If it returns a
    ``ChatResponse``, that becomes the response. Otherwise, if
    ``notify_user`` is True, a default error message is sent.
    """

    async def error_mw(ctx: Context, next_fn: Callable) -> None:
        try:
            await next_fn()
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            if handler:
                result = await handler(ctx, e)
                if result is not None:
                    ctx.response = result
                    return
            if notify_user:
                ctx.response = ChatResponse(text=f"处理消息失败: {e}")

    return error_mw
