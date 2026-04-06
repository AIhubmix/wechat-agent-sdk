"""Test middleware chain."""

import pytest

from wechat_agent_sdk import ChatRequest, ChatResponse, Context, MiddlewareChain, make_error_middleware


def _make_ctx(text="hello"):
    return Context(
        request=ChatRequest(conversation_id="user_1", text=text),
        account_id="test",
    )


@pytest.mark.asyncio
async def test_chain_executes_handler():
    chain = MiddlewareChain()
    ctx = _make_ctx()

    async def handler(ctx):
        ctx.response = ChatResponse(text="reply")

    await chain.execute(ctx, handler)
    assert ctx.response.text == "reply"


@pytest.mark.asyncio
async def test_chain_middleware_order():
    chain = MiddlewareChain()
    order = []

    async def mw1(ctx, next_fn):
        order.append("mw1_before")
        await next_fn()
        order.append("mw1_after")

    async def mw2(ctx, next_fn):
        order.append("mw2_before")
        await next_fn()
        order.append("mw2_after")

    chain.use(mw1)
    chain.use(mw2)

    async def handler(ctx):
        order.append("handler")

    await chain.execute(_make_ctx(), handler)
    assert order == ["mw1_before", "mw2_before", "handler", "mw2_after", "mw1_after"]


@pytest.mark.asyncio
async def test_chain_short_circuit():
    """Middleware that doesn't call next() should short-circuit."""
    chain = MiddlewareChain()
    handler_called = False

    async def blocker(ctx, next_fn):
        ctx.response = ChatResponse(text="blocked")
        # deliberately not calling next_fn()

    chain.use(blocker)

    async def handler(ctx):
        nonlocal handler_called
        handler_called = True

    ctx = _make_ctx()
    await chain.execute(ctx, handler)

    assert ctx.response.text == "blocked"
    assert handler_called is False


@pytest.mark.asyncio
async def test_chain_di_via_extra():
    """Middleware can inject data via ctx.extra (aiogram DI pattern)."""
    chain = MiddlewareChain()

    async def inject_db(ctx, next_fn):
        ctx.extra["db"] = "fake_db_session"
        await next_fn()

    chain.use(inject_db)

    async def handler(ctx):
        assert ctx.extra["db"] == "fake_db_session"
        ctx.response = ChatResponse(text="ok")

    ctx = _make_ctx()
    await chain.execute(ctx, handler)
    assert ctx.response.text == "ok"


@pytest.mark.asyncio
async def test_error_middleware_default():
    """Default error middleware sends error message to user."""
    chain = MiddlewareChain()
    chain.use(make_error_middleware())

    async def handler(ctx):
        raise ValueError("boom")

    ctx = _make_ctx()
    await chain.execute(ctx, handler)
    assert "处理消息失败" in ctx.response.text
    assert "boom" in ctx.response.text


@pytest.mark.asyncio
async def test_error_middleware_custom_handler():
    """Custom error handler can return a response."""

    async def my_handler(ctx, error):
        return ChatResponse(text=f"自定义错误: {error}")

    chain = MiddlewareChain()
    chain.use(make_error_middleware(handler=my_handler))

    async def handler(ctx):
        raise RuntimeError("oops")

    ctx = _make_ctx()
    await chain.execute(ctx, handler)
    assert ctx.response.text == "自定义错误: oops"


@pytest.mark.asyncio
async def test_error_middleware_silent():
    """Error middleware with notify_user=False should not set response."""

    chain = MiddlewareChain()
    chain.use(make_error_middleware(notify_user=False))

    async def handler(ctx):
        raise RuntimeError("silent error")

    ctx = _make_ctx()
    await chain.execute(ctx, handler)
    assert ctx.response is None
