# wechat-agent-sdk

English | [中文](./README_zh.md)

WeChat AI Agent bridge framework — connect any AI backend to WeChat with a simple Agent interface.

Supports [ACP (Agent Client Protocol)](https://agentclientprotocol.com/) to bridge Claude Code, Codex, Kimi, and other ACP-compatible agents directly to WeChat.

> This is not an official WeChat project. Built on the iLink Bot API, for learning and research purposes only.

## Features

- **Minimal interface** — implement a single `chat()` method to connect to WeChat
- **ACP protocol support** — bridge Claude Code, Codex, Kimi CLI, and other ACP agents
- **Zero infrastructure** — runs locally, no public server, Redis, or database required
- **Resume on restart** — picks up where it left off using persisted cursor
- **Auto reconnect** — built-in exponential backoff and session expiry recovery
- **Markdown conversion** — automatically strips markdown to WeChat-friendly plain text

## Installation

```bash
pip install wechat-agent-sdk
```

Optional dependencies:

```bash
pip install 'wechat-agent-sdk[qr]'     # Terminal QR code display
pip install 'wechat-agent-sdk[acp]'     # ACP protocol support
pip install 'wechat-agent-sdk[openai]'  # OpenAI integration
```

> Requires Python >= 3.11

## Quick Start

### 1. Echo Bot (Minimal Example)

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class EchoAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=f"You said: {request.text}")

async def main():
    bot = WeChatBot(agent=EchoAgent())
    await bot.run()  # Shows QR code on first run, scan to login

asyncio.run(main())
```

On first run, a QR code is displayed in the terminal (requires the `qrcode` dependency). Scan it with WeChat to confirm. Credentials are saved to `~/.wechat-agent-sdk/accounts.json` and reused on subsequent runs.

### 2. Connect Claude Code via ACP

[ACP (Agent Client Protocol)](https://agentclientprotocol.com/) is an open agent communication protocol. If you have an ACP-compatible agent, you can bridge it to WeChat directly:

```python
import asyncio
from wechat_agent_sdk import WeChatBot
from wechat_agent_sdk.acp.adapter import AcpAgent

async def main():
    # command is the ACP agent's launch command
    agent = AcpAgent(command="claude-agent-acp")
    bot = WeChatBot(agent=agent)
    await bot.run()

asyncio.run(main())
```

Supported ACP agents:

| Agent | Command | Reference |
|-------|---------|-----------|
| Claude Code | `claude-agent-acp` | [zed-industries/claude-agent-acp](https://github.com/zed-industries/claude-agent-acp) |
| Codex | `codex-acp` | [zed-industries/codex-acp](https://github.com/zed-industries/codex-acp) |
| Kimi CLI | `kimi` (args: `["acp"]`) | [moonshotai/kimi-cli](https://github.com/nicepkg/kimi-cli) |

```python
# Kimi CLI example (command + args passed separately)
agent = AcpAgent(command="kimi", args=["acp"])
```

### 3. OpenAI / Compatible APIs

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class OpenAIAgent(Agent):
    def __init__(self):
        self._conversations: dict[str, list[dict]] = {}

    async def on_start(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        history = self._conversations.setdefault(request.conversation_id, [])
        history.append({"role": "user", "content": request.text})

        resp = await self._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "You are a helpful assistant."}] + history[-20:],
        )
        reply = resp.choices[0].message.content or ""
        history.append({"role": "assistant", "content": reply})
        return ChatResponse(text=reply)

async def main():
    bot = WeChatBot(agent=OpenAIAgent())
    await bot.run()

asyncio.run(main())
```

Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API Key |
| `OPENAI_BASE_URL` | No | Custom API base URL (for OpenAI-compatible services) |

## API Reference

### Agent (Abstract Base Class)

```python
from wechat_agent_sdk import Agent

class MyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a single message and return a reply. (Required)"""
        ...

    async def on_start(self) -> None:
        """Called when the bot starts. Optional, for initialization."""
        ...

    async def on_stop(self) -> None:
        """Called when the bot stops. Optional, for cleanup."""
        ...
```

### ChatRequest

Inbound message, parsed from WeChat by the SDK.

| Field | Type | Description |
|-------|------|-------------|
| `conversation_id` | `str` | User wxid (DM) or group ID (group chat) |
| `text` | `str` | Text content (voice messages are auto-transcribed) |
| `media` | `MediaInfo \| None` | Attachment info (image/audio/video/file) |
| `message_id` | `str` | Unique message ID (for deduplication) |
| `group_id` | `str \| None` | Group ID (in group chats) |
| `sender_id` | `str \| None` | Sender wxid (in group chats) |
| `sender_name` | `str \| None` | Sender nickname (in group chats) |
| `is_at_bot` | `bool` | Whether the bot was @mentioned (in group chats) |
| `raw` | `dict \| None` | Raw iLink message (for advanced use) |

### ChatResponse

Reply from an Agent back to WeChat.

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str \| None` | Reply text. Markdown is supported and auto-stripped before sending |
| `media` | `MediaResponseInfo \| None` | Reply media (image/video/file) |

`MediaResponseInfo`:

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | `"image"` / `"video"` / `"file"` |
| `url` | `str` | Local file path or HTTPS URL |
| `file_name` | `str \| None` | Filename hint |

### WeChatBot

Orchestrates the full bot lifecycle: login -> message loop -> graceful shutdown.

```python
bot = WeChatBot(
    agent=my_agent,            # Agent instance (required)
    account_id="default",      # Account identifier (for multi-account setups)
    storage=JsonFileStorage(), # Persistence backend (pluggable)
    token="",                  # Provide token directly (skip QR login)
    api_base_url="",           # Custom API base URL
)

# Option 1: All-in-one (auto login + start receiving messages)
await bot.run()

# Option 2: Step-by-step control
await bot.login()   # QR code login, returns token
await bot.run()     # Start message loop
await bot.stop()    # Graceful shutdown
```

### AcpAgent

Bridge external agents via the ACP protocol.

```python
from wechat_agent_sdk.acp.adapter import AcpAgent

agent = AcpAgent(
    command="claude-agent-acp",  # ACP agent launch command
    args=[],                      # Command arguments
    cwd=None,                     # Working directory (defaults to cwd)
    env=None,                     # Additional environment variables
    auto_approve=True,            # Auto-approve agent permission requests
)
```

The SDK spawns the ACP agent as a subprocess and communicates via JSON-RPC over stdio. Each WeChat conversation gets an independent ACP session with full multi-turn context.

### Custom Storage

The default storage is `JsonFileStorage` (file: `~/.wechat-agent-sdk/accounts.json`). Implement the `AccountStorage` abstract class to use Redis, SQLite, or any other backend:

```python
from wechat_agent_sdk import AccountStorage

class RedisStorage(AccountStorage):
    async def load_token(self, account_id: str) -> str | None: ...
    async def save_token(self, account_id: str, token: str) -> None: ...
    async def load_cursor(self, account_id: str) -> str | None: ...
    async def save_cursor(self, account_id: str, cursor: str) -> None: ...

bot = WeChatBot(agent=my_agent, storage=RedisStorage())
```

## Supported Message Types

### Inbound (WeChat -> Agent)

| Type | `ChatRequest` behavior |
|------|----------------------|
| Text | `text` field contains the message |
| Image | `text` is `"[图片]"`, `media` contains the downloaded local path |
| Voice | If transcribed, `text` contains the transcription; otherwise `text` is `"[语音]"` |
| Video | `text` is `"[视频]"` |
| File | `text` is `"[文件: xxx.pdf]"` |
| Quote | Quoted text is prepended, e.g. `"[引用: original] new message"` |

### Outbound (Agent -> WeChat)

| Type | Usage |
|------|-------|
| Text | `ChatResponse(text="...")` |
| Long text | Auto-split at paragraph boundaries (max 4000 chars per message) |
| Markdown | Auto-stripped to plain text (removes `**`, `#`, code fences, etc.) |
| Image | `ChatResponse(media=MediaResponseInfo(type="image", url="..."))` (planned) |

## Technical Details

- **Long polling** (`getUpdates`) for message retrieval — no public server needed
- **Deduplication**: OrderedDict sliding window (1000 entries) by `message_id`
- **Typing indicator**: automatically shown before processing, cancelled after reply
- **Typing ticket cache**: 24-hour TTL
- **Error retry**: up to 3 consecutive failures, then 30s cooldown
- **Session expiry**: `errcode -14` triggers 1-hour cooldown with auto-recovery
- **State persistence**: token and cursor saved periodically (5s interval)

## Project Structure

```
src/wechat_agent_sdk/
├── __init__.py              # Public API exports
├── agent.py                 # Agent abstract base class
├── types.py                 # ChatRequest, ChatResponse, MediaInfo
├── api/
│   ├── client.py            # ILinkBotClient (5 API endpoints)
│   ├── auth.py              # QR code login flow
│   └── types.py             # iLink API data models
├── messaging/
│   ├── process.py           # Inbound message parsing
│   ├── send.py              # Outbound send + markdown conversion + text splitting
│   └── monitor.py           # Long-poll message loop
├── acp/
│   └── adapter.py           # AcpAgent: ACP subprocess bridge adapter
├── account/
│   ├── manager.py           # WeChatBot: account lifecycle orchestration
│   └── storage.py           # AccountStorage ABC + JsonFileStorage
└── utils/
    └── markdown.py          # strip_markdown()
```

## Roadmap

- [x] Single account, direct messages (text)
- [x] ACP protocol adapter
- [ ] Media messages (image/video/file)
- [ ] Group chat support (@bot filtering)
- [ ] Multi-account management
- [ ] Go SDK
- [ ] Node.js SDK

## Acknowledgements

- [wong2/weixin-agent-sdk](https://github.com/wong2/weixin-agent-sdk) — architecture reference
- [m1heng/claude-plugin-weixin](https://github.com/m1heng/claude-plugin-weixin) — Claude integration reference
- [Agent Client Protocol](https://agentclientprotocol.com/) — ACP specification

## License

MIT
