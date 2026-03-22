# wechat-agent-sdk

English | [中文](./README_zh.md)

WeChat AI Agent bridge framework — connect any AI backend to WeChat with a simple Agent interface.

Supports [ACP (Agent Client Protocol)](https://agentclientprotocol.com/) to bridge Claude Code, Codex, Kimi, and other ACP-compatible agents directly to WeChat.

> This is not an official WeChat project. Built on the iLink Bot API, for learning and research purposes only.

## How It Works

1. Install this SDK and create a Python script that implements the `Agent` interface
2. The SDK handles WeChat login (QR code), message polling, deduplication, and reply delivery
3. You only need to implement one method: `chat(request) -> response`

## Installation

```bash
pip install wechat-agent-sdk
```

Install with optional dependencies based on your use case:

```bash
# Terminal QR code display (recommended)
pip install 'wechat-agent-sdk[qr]'

# ACP protocol support (required for Claude Code / Codex / Kimi integration)
pip install 'wechat-agent-sdk[acp]'

# OpenAI integration
pip install 'wechat-agent-sdk[openai]'
```

> Requires Python >= 3.11

## Implementation Guide

> **Note for AI Agents**: This documentation is designed for AI agents (e.g. Claude Code) to read and follow. To implement WeChat integration, write code based on the patterns below — do not run the scripts in `examples/` directly. The `examples/` directory is only for reference.

To integrate WeChat with an AI backend, create a Python script with the following pattern:

### Step 1: Implement the Agent Interface

Subclass `Agent` and implement the `chat()` method. This is the only required method. The SDK calls it for every inbound WeChat message and sends the returned `ChatResponse` back to the user.

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class MyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        # request.text contains the user's message
        # request.conversation_id identifies the user/conversation
        # Return a ChatResponse with the reply text
        return ChatResponse(text=f"You said: {request.text}")

async def main():
    bot = WeChatBot(agent=MyAgent())
    await bot.run()

asyncio.run(main())
```

### Step 2: Run and Login

Run the script. On first run, a QR code is displayed in the terminal (requires the `qrcode` dependency). Scan it with WeChat to login. Credentials are persisted to `~/.wechat-agent-sdk/accounts.json` and reused on subsequent runs.

---

## Integration Patterns

### Pattern A: Connect Claude Code via ACP

Use this pattern to bridge [Claude Code](https://code.claude.com/) or other ACP-compatible agents to WeChat.

**Prerequisites:**

1. Install the ACP adapter for your agent (requires Node.js >= 18):

```bash
# Claude Code ACP adapter
npm install -g @zed-industries/claude-code-acp
```

> Pre-built binaries are also available on the [Releases page](https://github.com/zed-industries/claude-agent-acp/releases).

2. Install the SDK with ACP support:

```bash
pip install 'wechat-agent-sdk[acp,qr]'
```

**Implementation:**

```python
import asyncio
from wechat_agent_sdk import WeChatBot
from wechat_agent_sdk.acp.adapter import AcpAgent

async def main():
    agent = AcpAgent(
        command="claude-agent-acp",       # ACP agent launch command
        permission_mode="bypassPermissions",  # Required: skip terminal permission prompts
    )
    bot = WeChatBot(agent=agent)
    await bot.run()

asyncio.run(main())
```

**Supported ACP agents:**

| Agent | Install | Command | Reference |
|-------|---------|---------|-----------|
| Claude Code | `npm i -g @zed-industries/claude-code-acp` | `claude-agent-acp` | [zed-industries/claude-agent-acp](https://github.com/zed-industries/claude-agent-acp) |
| Codex | `npm i -g @openai/codex-acp` | `codex-acp` | [zed-industries/codex-acp](https://github.com/zed-industries/codex-acp) |
| Kimi CLI | `npm i -g kimi-cli` | `kimi` (args: `["acp"]`) | [moonshotai/kimi-cli](https://github.com/nicepkg/kimi-cli) |

```python
# Kimi CLI example
agent = AcpAgent(command="kimi", args=["acp"])
```

### Pattern B: OpenAI / Compatible APIs

Use this pattern for OpenAI, or any API with an OpenAI-compatible interface (e.g. DeepSeek, Moonshot, local models via Ollama).

**Prerequisites:**

```bash
pip install 'wechat-agent-sdk[openai,qr]'
```

Set the `OPENAI_API_KEY` environment variable. Optionally set `OPENAI_BASE_URL` for compatible APIs.

**Implementation:**

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

### Pattern C: Custom Agent

Implement any custom logic. The `Agent` interface is intentionally minimal:

```python
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse

class MyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a single message and return a reply. (Required)"""
        ...

    async def on_start(self) -> None:
        """Called once when the bot starts. Use for initialization (e.g. loading models)."""
        ...

    async def on_stop(self) -> None:
        """Called once when the bot stops. Use for cleanup."""
        ...
```

## API Reference

### ChatRequest

Inbound message from WeChat, parsed by the SDK.

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

Reply from the Agent back to WeChat.

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str \| None` | Reply text. Markdown is auto-stripped to plain text before sending |
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

Bridge external agents via the ACP protocol. **Requires the ACP adapter to be installed separately** (see Integration Patterns above).

```python
from wechat_agent_sdk.acp.adapter import AcpAgent

agent = AcpAgent(
    command="claude-agent-acp",           # ACP agent launch command
    args=[],                               # Command arguments
    cwd=None,                              # Working directory (defaults to cwd)
    env=None,                              # Additional environment variables
    auto_approve=True,                     # Auto-approve ACP protocol permission requests
    permission_mode="bypassPermissions",   # Agent-level permission mode (see below)
)
```

**Permission mode** (`permission_mode`) — ACP agents like `claude-agent-acp` have their own internal permission system separate from the ACP protocol. In a non-interactive environment like WeChat, the agent cannot prompt for terminal confirmation and will reply "I don't have permission" unless configured otherwise. This parameter sets the `ACP_PERMISSION_MODE` environment variable:

| Mode | Behavior |
|------|----------|
| `"bypassPermissions"` | Skip all permission prompts (**default, recommended for WeChat**) |
| `"acceptEdits"` | Auto-approve file edits; other operations still require confirmation |
| `"default"` | Ask for confirmation on everything (will fail in non-interactive environments) |

**Streaming** — When the ACP agent executes tool calls (e.g. reading files, running commands), text accumulated before each tool call is automatically flushed to WeChat, so the user sees incremental output instead of waiting for the entire response.

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

## Acknowledgements

- [wong2/weixin-agent-sdk](https://github.com/wong2/weixin-agent-sdk) — architecture reference
- [m1heng/claude-plugin-weixin](https://github.com/m1heng/claude-plugin-weixin) — Claude integration reference
- [Agent Client Protocol](https://agentclientprotocol.com/) — ACP specification

## License

MIT
