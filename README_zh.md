# wechat-agent-sdk

[English](./README.md) | 中文

微信 AI Agent 桥接框架 — 通过简单的 Agent 接口将任意 AI 后端接入微信，也可作为传输层嵌入已有平台。

支持 [ACP (Agent Client Protocol)](https://agentclientprotocol.com/) 协议，可直接接入 Claude Code、Codex、Kimi 等 Agent。

> 本项目非微信官方项目，基于 iLink Bot API，仅供学习交流使用。

## 架构

SDK 采用两层架构设计：

```
┌─────────────────────────────────────────────────┐
│           Bot 层 (全栈模式)                      │
│  WeChatBot / Builder / Manager / Middleware      │
│  Agent.chat() 调度                               │
│  适用：独立开发者                                 │
└──────────────────────┬──────────────────────────┘
                       │ 内部调用
┌──────────────────────▼──────────────────────────┐
│         Transport 层 (薄适配层)                  │
│  WeChatTransport                                 │
│  连接 / 收消息 / 解析 / 发送 / 登录              │
│  适用：平台集成                                   │
└──────────────────────┬──────────────────────────┘
                       │ 内部调用
┌──────────────────────▼──────────────────────────┐
│              基础设施                             │
│  ILinkBotClient (7 个 API 端点)                  │
│  MediaPipeline (AES 加解密 + CDN 上传下载)       │
│  AccountStorage (JSON / Redis / SQLite)          │
└─────────────────────────────────────────────────┘
```

**独立开发者** 用 Bot 层 — 实现 `Agent.chat()`，调 `bot.run()`，搞定。

**平台集成方** 用 Transport 层 — 消费 `transport.messages()`，自己管路由/Agent/会话，调 `transport.send_text()` 回复。

## 安装

```bash
pip install wechat-agent-sdk
```

可选依赖：

```bash
pip install 'wechat-agent-sdk[qr]'       # 终端二维码显示
pip install 'wechat-agent-sdk[acp]'       # ACP 协议（Claude Code / Codex / Kimi）
pip install 'wechat-agent-sdk[openai]'    # OpenAI 集成
pip install 'wechat-agent-sdk[redis]'     # Redis 存储后端
pip install 'wechat-agent-sdk[sqlite]'    # SQLite 存储后端
pip install 'wechat-agent-sdk[all]'       # 全部
```

> 要求 Python >= 3.11

## 快速开始（Bot 层）

5 分钟跑起一个 bot：

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class EchoAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=f"你说了: {request.text}")

async def main():
    bot = WeChatBot(agent=EchoAgent())
    await bot.run()

asyncio.run(main())
```

使用 Builder 模式：

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

## Transport 层（平台集成）

适用于已有自己的 Agent 执行层、Pipeline、会话管理的平台。Transport 层只提供：连接、收消息、解析、发送。

```python
import asyncio
from wechat_agent_sdk import WeChatTransport, ParsedMessage

async def main():
    transport = WeChatTransport(
        account_id="bot_1",
        storage=my_redis_storage,
    )

    # Web 登录（平台有 Web UI 时用）
    session = await transport.request_login()
    # ... 在前端展示 session.qr_url ...
    result = await transport.check_login(session)

    # 或终端登录
    # await transport.login_terminal()

    # 收消息
    await transport.connect()
    async for raw_msg in transport.messages():
        parsed = transport.parse(raw_msg)
        if not parsed:
            continue

        # 平台自己处理：权限检查、会话管理、Agent 执行、SSE 流式...
        reply = await your_pipeline.handle(parsed)

        # 通过 transport 发回复
        await transport.send_text(parsed.conversation_id, reply, parsed.context_token)

    await transport.disconnect()

asyncio.run(main())
```

### Transport API

| 方法 | 说明 |
|------|------|
| `connect()` / `disconnect()` | 管理连接生命周期 |
| `messages()` | 异步迭代器 — 长轮询收消息（自动去重 + cursor） |
| `parse(raw)` | 解析原始 iLink 消息 → `ParsedMessage` |
| `send_text(chat_id, text)` | 发文本（自动去 markdown + 长文本拆分） |
| `send_text_raw(chat_id, text)` | 发原始文本（不处理） |
| `send_media(chat_id, data, type)` | 加密 + 上传 + 发媒体 |
| `download_media(media)` | 下载 + 解密媒体附件 |
| `send_typing(chat_id, start)` | 正在输入指示器 |
| `request_login()` | 获取 QR URL（Web 登录用） |
| `check_login(session)` | 轮询登录状态 |
| `login_terminal()` | 终端交互式二维码登录 |
| `logout()` | 清除 token，强制重登 |
| `activate_token(token)` | 注入 token（平台重登后调用） |
| `needs_login` | 属性：是否需要登录 |

## 集成模式

### 模式 A：通过 ACP 接入 Claude Code

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

支持的 ACP Agent：

| Agent | 安装 | Command |
|-------|------|---------|
| Claude Code | `npm i -g @zed-industries/claude-code-acp` | `claude-agent-acp` |
| Codex | `npm i -g @openai/codex-acp` | `codex-acp` |
| Kimi CLI | `npm i -g kimi-cli` | `kimi` (args: `["acp"]`) |

### 模式 B：OpenAI / 兼容 API

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

### 模式 C：多账号

```python
from wechat_agent_sdk import WeChatBotManager

manager = WeChatBotManager(storage=my_storage, auto_restart=True)
manager.add_bot("bot_1", agent=AgentA())
manager.add_bot("bot_2", agent=AgentB())

await manager.start_all()
# manager.get_status() → {"bot_1": RUNNING, "bot_2": RUNNING}
await manager.stop_all()
```

## 中间件

Bot 层支持洋葱中间件链（借鉴 aiogram / Bot Framework）：

```python
async def logging_mw(ctx, next_fn):
    print(f"收到: {ctx.request.text}")
    await next_fn()  # 调用下一个中间件 / handler
    print(f"回复: {ctx.response.text if ctx.response else 'None'}")

async def rate_limit(ctx, next_fn):
    if is_rate_limited(ctx.request.conversation_id):
        ctx.response = ChatResponse(text="请稍后再试")
        return  # 短路，不调 next
    await next_fn()

bot = WeChatBot.builder().agent(my_agent).middleware(logging_mw).middleware(rate_limit).build()
```

错误处理：

```python
async def my_error_handler(ctx, error):
    await alert_ops_team(error)
    return ChatResponse(text="出了点问题，请重试")

bot = WeChatBot.builder().agent(my_agent).on_error(my_error_handler).build()
```

## 并发消息处理

Bot 层默认最多同时处理 10 条消息。当 `agent.chat()` 耗时较长（如 AcpAgent 调 Claude Code），其他用户的消息可并行处理，而非排队等待。

```python
# 默认 10 并发
bot = WeChatBot(agent=my_agent)

# 自定义并发上限
bot = WeChatBot(agent=my_agent, max_concurrent=20)

# Builder 模式
bot = WeChatBot.builder().agent(my_agent).max_concurrent(5).build()
```

通过 `asyncio.Semaphore` 控制上限，达到上限时新消息等待空位。Transport 层不管并发，平台集成方自行控制。

## 存储后端

| 后端 | 安装 | 用法 |
|------|------|------|
| JSON 文件（默认） | 内置 | `JsonFileStorage()` |
| Redis | `pip install 'wechat-agent-sdk[redis]'` | `from wechat_agent_sdk.account.redis_storage import RedisStorage` |
| SQLite | `pip install 'wechat-agent-sdk[sqlite]'` | `from wechat_agent_sdk.account.sqlite_storage import SqliteStorage` |

```python
from wechat_agent_sdk.account.redis_storage import RedisStorage

storage = RedisStorage(url="redis://localhost:6379", prefix="wechat-sdk")
bot = WeChatBot(agent=my_agent, storage=storage)
```

## API 参考

### ParsedMessage（Transport 层）

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `str` | 用户 wxid 或群 ID |
| `text` | `str` | 文本内容（语音自动转文字） |
| `media` | `list[MediaInfo]` | 所有媒体附件（支持多图） |
| `message_id` | `str` | 消息唯一 ID |
| `context_token` | `str` | 回复时必须回传 |
| `group_id` | `str \| None` | 群 ID |
| `sender_id` | `str \| None` | 发送者 wxid |
| `sender_name` | `str \| None` | 发送者昵称 |
| `is_at_bot` | `bool` | 是否 @了 Bot |
| `raw` | `dict \| None` | 原始 iLink 消息 |

### ChatRequest（Bot 层）

字段同 `ParsedMessage`，区别：`media` 为 `MediaInfo | None`（只取第一个附件），无 `context_token`（内部处理）。

### ChatResponse

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str \| None` | 回复文本（markdown 自动转纯文本） |
| `media` | `MediaResponseInfo \| None` | 回复媒体 |

### MediaInfo

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `str` | `"image"` / `"audio"` / `"video"` / `"file"` |
| `cdn_param` | `str` | CDN 加密查询参数（用于下载） |
| `aes_key` | `str` | Base64 AES 密钥 |
| `file_name` | `str \| None` | 原始文件名 |

下载媒体：`data = await transport.download_media(media_info)`

## 支持的消息类型

### 接收（微信 → Agent）

| 类型 | 行为 |
|------|------|
| 文本 | `text` 直接拿到文字 |
| 图片 | `text` 为 `"[图片]"`，`media` 含 CDN 引用可下载 |
| 语音 | 有转写则 `text` 为文字，否则 `"[语音]"` |
| 视频 | `text` 为 `"[视频]"`，`media` 含 CDN 引用 |
| 文件 | `text` 为 `"[文件: xxx.pdf]"`，`media` 含 CDN 引用 |
| 引用 | 引用文本拼入 `text`：`"[引用: 原文] 新消息"` |

### 发送（Agent → 微信）

| 类型 | 用法 |
|------|------|
| 文本 | `ChatResponse(text="...")` |
| 长文本 | 自动按段落拆分（每段最长 2000 字符） |
| Markdown | 自动转纯文本 |
| 图片/视频/文件 | `ChatResponse(media=MediaResponseInfo(type="image", url="路径或URL"))` |

## 项目结构

```
src/wechat_agent_sdk/
├── __init__.py              # 公共 API 导出
├── agent.py                 # Agent 抽象基类
├── types.py                 # ChatRequest, ChatResponse, MediaInfo
├── transport.py             # WeChatTransport + ParsedMessage（传输层）
├── middleware.py             # MiddlewareChain + Context（Bot 层）
├── api/
│   ├── client.py            # ILinkBotClient（7 个 API 端点）
│   ├── auth.py              # 登录流程 + LoginSession/LoginResult
│   └── types.py             # iLink API 数据模型
├── messaging/
│   ├── process.py           # 入站消息解析
│   ├── send.py              # 文本拆分 + markdown 转换
│   └── monitor.py           # 旧版 monitor（向后兼容保留）
├── media/
│   ├── crypto.py            # AES-128-ECB + 双格式 key 解码
│   └── cdn.py               # CDN 上传 / 下载
├── acp/
│   └── adapter.py           # AcpAgent: ACP 子进程桥接
├── account/
│   ├── manager.py           # WeChatBot + WeChatBotBuilder
│   ├── bot_manager.py       # WeChatBotManager（多账号）
│   ├── storage.py           # AccountStorage ABC + JsonFileStorage
│   ├── redis_storage.py     # RedisStorage（可选）
│   └── sqlite_storage.py    # SqliteStorage（可选）
└── utils/
    └── markdown.py          # strip_markdown()
```

## 致谢

- [wong2/weixin-agent-sdk](https://github.com/wong2/weixin-agent-sdk) — 架构设计参考
- [m1heng/claude-plugin-weixin](https://github.com/m1heng/claude-plugin-weixin) — Claude 集成参考
- [Agent Client Protocol](https://agentclientprotocol.com/) — ACP 协议规范

## License

MIT
