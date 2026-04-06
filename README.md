# wechat-agent-sdk

English | [中文](./README_zh.md)

WeChat AI Agent bridge framework — connect any AI backend to WeChat with a simple Agent interface, or embed as a transport layer in your platform.

Supports [ACP (Agent Client Protocol)](https://agentclientprotocol.com/) to bridge Claude Code, Codex, Kimi, and other ACP-compatible agents directly to WeChat.

> This is not an official WeChat project. Built on the iLink Bot API, for learning and research purposes only.

## Architecture

The SDK has a two-layer design:

```
┌─────────────────────────────────────────────────┐
│           Bot Layer (full-stack mode)            │
│  WeChatBot / Builder / Manager / Middleware      │
│  Agent.chat() dispatching                        │
│  For: standalone developers                      │
└──────────────────────┬──────────────────────────┘
                       │ uses internally
┌──────────────────────▼──────────────────────────┐
│         Transport Layer (headless mode)          │
│  WeChatTransport                                 │
│  connect / messages / parse / send / login       │
│  For: platform integration                       │
└──────────────────────┬──────────────────────────┘
                       │ uses internally
┌──────────────────────▼──────────────────────────┐
│              Infrastructure                      │
│  ILinkBotClient (7 API endpoints)                │
│  MediaPipeline (AES + CDN upload/download)       │
│  AccountStorage (JSON / Redis / SQLite)          │
└─────────────────────────────────────────────────┘
```

**Standalone developers** use the Bot layer — implement `Agent.chat()`, call `bot.run()`, done.

**Platform integrators** use the Transport layer — consume `transport.messages()`, handle routing/agents yourself, call `transport.send_text()` to reply.

## Installation

```bash
pip install wechat-agent-sdk
```

Optional dependencies:

```bash
pip install 'wechat-agent-sdk[qr]'       # Terminal QR code display
pip install 'wechat-agent-sdk[acp]'       # ACP protocol (Claude Code / Codex / Kimi)
pip install 'wechat-agent-sdk[openai]'    # OpenAI integration
pip install 'wechat-agent-sdk[redis]'     # Redis storage backend
pip install 'wechat-agent-sdk[sqlite]'    # SQLite storage backend
pip install 'wechat-agent-sdk[all]'       # Everything
```

> Requires Python >= 3.11

## Quick Start (Bot Layer)

For standalone developers who want a bot running in 5 minutes:

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class EchoAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=f"You said: {request.text}")

async def main():
    bot = WeChatBot(agent=EchoAgent())
    await bot.run()

asyncio.run(main())
```

Using the Builder pattern:

```python
bot = (
    WeChatBot.builder()
    .agent(EchoAgent())
    .account_id("my_bot")
    .storage(RedisStorage("redis://localhost"))
    .middleware(rate_limit_middleware)
    .on_error(my_error_handler)
    .build()
)
await bot.run()
```

## Transport Layer (Platform Integration)

For platforms that have their own agent execution layer, pipeline, and session management. The Transport layer provides only: connect, receive, parse, send.

```python
import asyncio
from wechat_agent_sdk import WeChatTransport, ParsedMessage

async def main():
    transport = WeChatTransport(
        account_id="bot_1",
        storage=my_redis_storage,
    )

    # Web login (for platforms with web UI)
    session = await transport.request_login()
    # ... show session.qr_url in your web UI ...
    result = await transport.check_login(session)

    # Or terminal login
    # await transport.login_terminal()

    # Receive messages
    await transport.connect()
    async for raw_msg in transport.messages():
        parsed = transport.parse(raw_msg)
        if not parsed:
            continue

        # Your platform handles everything from here:
        # permission checks, session management, agent execution, SSE streaming...
        reply = await your_pipeline.handle(parsed)

        # Send reply via transport
        await transport.send_text(parsed.conversation_id, reply, parsed.context_token)

    await transport.disconnect()

asyncio.run(main())
```

### Transport API

| Method | Description |
|--------|-------------|
| `connect()` / `disconnect()` | Manage connection lifecycle |
| `messages()` | Async iterator — long-poll for messages (auto dedup + cursor) |
| `parse(raw)` | Parse raw iLink message → `ParsedMessage` |
| `send_text(chat_id, text)` | Send text (auto markdown strip + split) |
| `send_text_raw(chat_id, text)` | Send raw text (no processing) |
| `send_media(chat_id, data, type)` | Encrypt + upload + send media |
| `download_media(media)` | Download + decrypt media attachment |
| `send_typing(chat_id, start)` | Typing indicator |
| `request_login()` | Get QR URL for web login |
| `check_login(session)` | Poll login status |
| `login_terminal()` | Interactive terminal QR login |
| `logout()` | Clear token, force re-login |
| `activate_token(token)` | Inject token (after platform re-login) |
| `needs_login` | Property: True when no valid token |

## Integration Patterns

### Pattern A: Claude Code via ACP

```bash
npm install -g @zed-industries/claude-code-acp
pip install 'wechat-agent-sdk[acp,qr]'
```

```python
from wechat_agent_sdk import WeChatBot
from wechat_agent_sdk.acp.adapter import AcpAgent

agent = AcpAgent(command="claude-agent-acp", permission_mode="bypassPermissions")
bot = WeChatBot(agent=agent)
await bot.run()
```

Supported ACP agents:

| Agent | Install | Command |
|-------|---------|---------|
| Claude Code | `npm i -g @zed-industries/claude-code-acp` | `claude-agent-acp` |
| Codex | `npm i -g @openai/codex-acp` | `codex-acp` |
| Kimi CLI | `npm i -g kimi-cli` | `kimi` (args: `["acp"]`) |

### Pattern B: OpenAI / Compatible APIs

```python
class OpenAIAgent(Agent):
    async def on_start(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        resp = await self._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": request.text}],
        )
        return ChatResponse(text=resp.choices[0].message.content)
```

### Pattern C: Multi-Account

```python
from wechat_agent_sdk import WeChatBotManager

manager = WeChatBotManager(storage=my_storage, auto_restart=True)
manager.add_bot("bot_1", agent=AgentA())
manager.add_bot("bot_2", agent=AgentB())

await manager.start_all()
# manager.get_status() → {"bot_1": RUNNING, "bot_2": RUNNING}
await manager.stop_all()
```

## Middleware

Bot layer supports an onion middleware chain (inspired by aiogram / Bot Framework):

```python
async def logging_mw(ctx, next_fn):
    print(f"Received: {ctx.request.text}")
    await next_fn()  # call next middleware / handler
    print(f"Replied: {ctx.response.text if ctx.response else 'None'}")

async def rate_limit(ctx, next_fn):
    if is_rate_limited(ctx.request.conversation_id):
        ctx.response = ChatResponse(text="Please slow down")
        return  # short-circuit, don't call next
    await next_fn()

bot = WeChatBot.builder().agent(my_agent).middleware(logging_mw).middleware(rate_limit).build()
```

Error handling via middleware:

```python
async def my_error_handler(ctx, error):
    await alert_ops_team(error)
    return ChatResponse(text="Something went wrong, please retry")

bot = WeChatBot.builder().agent(my_agent).on_error(my_error_handler).build()
```

## Concurrent Message Handling

By default, the Bot layer processes up to 10 messages concurrently. When `agent.chat()` takes a long time (e.g. AcpAgent calling Claude Code), other users' messages are handled in parallel instead of queuing.

```python
# Default: 10 concurrent handlers
bot = WeChatBot(agent=my_agent)

# Custom concurrency limit
bot = WeChatBot(agent=my_agent, max_concurrent=20)

# Via builder
bot = WeChatBot.builder().agent(my_agent).max_concurrent(5).build()
```

Bounded by `asyncio.Semaphore` — when the limit is reached, new messages wait until a slot opens. Transport layer does not manage concurrency; platform integrators control their own.

## Storage Backends

| Backend | Install | Usage |
|---------|---------|-------|
| JSON file (default) | built-in | `JsonFileStorage()` |
| Redis | `pip install 'wechat-agent-sdk[redis]'` | `from wechat_agent_sdk.account.redis_storage import RedisStorage` |
| SQLite | `pip install 'wechat-agent-sdk[sqlite]'` | `from wechat_agent_sdk.account.sqlite_storage import SqliteStorage` |

```python
from wechat_agent_sdk.account.redis_storage import RedisStorage

storage = RedisStorage(url="redis://localhost:6379", prefix="wechat-sdk")
bot = WeChatBot(agent=my_agent, storage=storage)
```

## API Reference

### ParsedMessage (Transport layer)

| Field | Type | Description |
|-------|------|-------------|
| `conversation_id` | `str` | User wxid (DM) or group ID |
| `text` | `str` | Text content (voice auto-transcribed) |
| `media` | `list[MediaInfo]` | All media attachments (supports multi-image) |
| `message_id` | `str` | Unique message ID |
| `context_token` | `str` | Must echo back when replying |
| `group_id` | `str \| None` | Group ID (group chats) |
| `sender_id` | `str \| None` | Sender wxid (group chats) |
| `sender_name` | `str \| None` | Sender nickname (group chats) |
| `is_at_bot` | `bool` | Whether bot was @mentioned |
| `raw` | `dict \| None` | Raw iLink message |

### ChatRequest (Bot layer)

Same fields as `ParsedMessage` except `media` is `MediaInfo | None` (first attachment only) and no `context_token` (handled internally).

### ChatResponse

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str \| None` | Reply text (markdown auto-stripped) |
| `media` | `MediaResponseInfo \| None` | Reply media (image/video/file) |

### MediaInfo

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | `"image"` / `"audio"` / `"video"` / `"file"` |
| `cdn_param` | `str` | CDN encrypted query param (for download) |
| `aes_key` | `str` | Base64 AES key |
| `file_name` | `str \| None` | Original filename |

Download media: `data = await transport.download_media(media_info)`

## Supported Message Types

### Inbound (WeChat → Agent)

| Type | Behavior |
|------|----------|
| Text | `text` contains the message |
| Image | `text` is `"[图片]"`, `media` contains CDN reference for download |
| Voice | Transcribed text if available, else `"[语音]"` |
| Video | `text` is `"[视频]"`, `media` contains CDN reference |
| File | `text` is `"[文件: xxx.pdf]"`, `media` contains CDN reference |
| Quote | Quoted text prepended: `"[引用: original] new message"` |

### Outbound (Agent → WeChat)

| Type | Usage |
|------|-------|
| Text | `ChatResponse(text="...")` |
| Long text | Auto-split at paragraph boundaries (max 2000 chars) |
| Markdown | Auto-stripped to plain text |
| Image/Video/File | `ChatResponse(media=MediaResponseInfo(type="image", url="path_or_url"))` |

## Project Structure

```
src/wechat_agent_sdk/
├── __init__.py              # Public API exports
├── agent.py                 # Agent abstract base class
├── types.py                 # ChatRequest, ChatResponse, MediaInfo
├── transport.py             # WeChatTransport + ParsedMessage (transport layer)
├── middleware.py             # MiddlewareChain + Context (bot layer)
├── api/
│   ├── client.py            # ILinkBotClient (7 API endpoints)
│   ├── auth.py              # Login flow + LoginSession/LoginResult
│   └── types.py             # iLink API data models
├── messaging/
│   ├── process.py           # Inbound message parsing
│   ├── send.py              # Text splitting + markdown conversion
│   └── monitor.py           # Legacy monitor (kept for backward compat)
├── media/
│   ├── crypto.py            # AES-128-ECB + dual-format key decoding
│   └── cdn.py               # CDN upload / download
├── acp/
│   └── adapter.py           # AcpAgent: ACP subprocess bridge
├── account/
│   ├── manager.py           # WeChatBot + WeChatBotBuilder
│   ├── bot_manager.py       # WeChatBotManager (multi-account)
│   ├── storage.py           # AccountStorage ABC + JsonFileStorage
│   ├── redis_storage.py     # RedisStorage (optional)
│   └── sqlite_storage.py    # SqliteStorage (optional)
└── utils/
    └── markdown.py          # strip_markdown()
```

## Acknowledgements

- [wong2/weixin-agent-sdk](https://github.com/wong2/weixin-agent-sdk) — architecture reference
- [m1heng/claude-plugin-weixin](https://github.com/m1heng/claude-plugin-weixin) — Claude integration reference
- [Agent Client Protocol](https://agentclientprotocol.com/) — ACP specification

## License

MIT
