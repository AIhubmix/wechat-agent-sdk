# wechat-agent-sdk

[English](./README.md) | 中文

微信 AI Agent 桥接框架 — 通过简单的 Agent 接口，将任意 AI 后端接入微信。

支持 [ACP (Agent Client Protocol)](https://agentclientprotocol.com/) 协议，可直接接入 Claude Code、Codex、Kimi 等 Agent。

> 本项目非微信官方项目，基于 iLink Bot API，仅供学习交流使用。

## 特性

- **极简接口** — 只需实现一个 `chat()` 方法即可接入微信
- **ACP 协议支持** — 通过 ACP 协议桥接 Claude Code、Codex、Kimi CLI 等 Agent
- **零基础设施** — 纯本地运行，无需公网服务器、Redis 或数据库
- **断点续传** — 重启后从上次位置继续接收消息
- **自动重连** — 内置指数退避、会话过期重连
- **Markdown 转换** — 回复文本中的 markdown 自动转为微信友好的纯文本

## 安装

```bash
pip install wechat-agent-sdk
```

可选依赖：

```bash
pip install 'wechat-agent-sdk[qr]'     # 终端二维码显示
pip install 'wechat-agent-sdk[acp]'     # ACP 协议支持
pip install 'wechat-agent-sdk[openai]'  # OpenAI 集成
```

> 要求 Python >= 3.11

## 快速开始

### 1. Echo Bot（最简示例）

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class EchoAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=f"你说了: {request.text}")

async def main():
    bot = WeChatBot(agent=EchoAgent())
    await bot.run()  # 首次运行会弹出二维码，扫码登录

asyncio.run(main())
```

运行后终端会显示二维码（需安装 `qrcode` 依赖），用微信扫码确认即可。登录信息会保存到 `~/.wechat-agent-sdk/accounts.json`，下次启动自动复用。

### 2. 通过 ACP 接入 Claude Code

[ACP (Agent Client Protocol)](https://agentclientprotocol.com/) 是一个开放的 Agent 通信协议。如果你有兼容 ACP 的 Agent，可以直接桥接到微信：

```python
import asyncio
from wechat_agent_sdk import WeChatBot
from wechat_agent_sdk.acp.adapter import AcpAgent

async def main():
    # command 是 ACP agent 的启动命令
    agent = AcpAgent(command="claude-agent-acp")
    bot = WeChatBot(agent=agent)
    await bot.run()

asyncio.run(main())
```

支持的 ACP Agent 示例：

| Agent | command | 参考 |
|-------|---------|------|
| Claude Code | `claude-agent-acp` | [zed-industries/claude-agent-acp](https://github.com/zed-industries/claude-agent-acp) |
| Codex | `codex-acp` | [zed-industries/codex-acp](https://github.com/zed-industries/codex-acp) |
| Kimi CLI | `kimi` (args: `["acp"]`) | [moonshotai/kimi-cli](https://github.com/nicepkg/kimi-cli) |

```python
# Kimi CLI 示例（command + args 分开传）
agent = AcpAgent(command="kimi", args=["acp"])
```

### 3. OpenAI / 兼容 API

```python
import asyncio
import os
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
            messages=[{"role": "system", "content": "你是一个友好的AI助手。"}] + history[-20:],
        )
        reply = resp.choices[0].message.content or ""
        history.append({"role": "assistant", "content": reply})
        return ChatResponse(text=reply)

async def main():
    bot = WeChatBot(agent=OpenAIAgent())
    await bot.run()

asyncio.run(main())
```

环境变量：

| 变量 | 必填 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | 是 | OpenAI API Key |
| `OPENAI_BASE_URL` | 否 | 自定义 API 地址（兼容 OpenAI 接口的第三方服务） |

## API 参考

### Agent（抽象基类）

```python
from wechat_agent_sdk import Agent

class MyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """处理单条消息并返回回复。（必须实现）"""
        ...

    async def on_start(self) -> None:
        """Bot 启动时调用。可选，用于初始化资源。"""
        ...

    async def on_stop(self) -> None:
        """Bot 停止时调用。可选，用于清理资源。"""
        ...
```

### ChatRequest

入站消息，由 SDK 从微信消息解析而来。

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `str` | 用户 wxid（私聊）或群 ID（群聊） |
| `text` | `str` | 文本内容（语音消息会自动转为文字） |
| `media` | `MediaInfo \| None` | 附件信息（图片/语音/视频/文件） |
| `message_id` | `str` | 消息唯一 ID（可用于去重） |
| `group_id` | `str \| None` | 群 ID（群聊时） |
| `sender_id` | `str \| None` | 发送者 wxid（群聊时） |
| `sender_name` | `str \| None` | 发送者昵称（群聊时） |
| `is_at_bot` | `bool` | 是否 @了 Bot（群聊时） |
| `raw` | `dict \| None` | 原始 iLink 消息（高级用途） |

### ChatResponse

Agent 返回给微信的回复。

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str \| None` | 回复文本。支持 markdown，发送前自动转纯文本 |
| `media` | `MediaResponseInfo \| None` | 回复媒体（图片/视频/文件） |

`MediaResponseInfo`:

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `str` | `"image"` / `"video"` / `"file"` |
| `url` | `str` | 本地文件路径或 HTTPS URL |
| `file_name` | `str \| None` | 文件名提示 |

### WeChatBot

编排整个 Bot 生命周期：登录 → 消息循环 → 优雅停机。

```python
bot = WeChatBot(
    agent=my_agent,          # Agent 实例（必填）
    account_id="default",    # 账户标识（多账户时区分不同登录）
    storage=JsonFileStorage(), # 持久化后端（可替换）
    token="",                # 直接提供 token（跳过扫码）
    api_base_url="",         # 自定义 API 地址
)

# 方式一：一步到位（自动登录 + 开始接收消息）
await bot.run()

# 方式二：分步控制
await bot.login()   # 扫码登录，返回 token
await bot.run()     # 开始消息循环
await bot.stop()    # 优雅停机
```

### AcpAgent

通过 ACP 协议桥接外部 Agent。

```python
from wechat_agent_sdk.acp.adapter import AcpAgent

agent = AcpAgent(
    command="claude-agent-acp",  # ACP agent 启动命令
    args=[],                      # 命令参数
    cwd=None,                     # 工作目录（默认当前目录）
    env=None,                     # 额外环境变量
    auto_approve=True,            # 自动批准 Agent 的权限请求
)
```

SDK 会以子进程方式启动 ACP Agent，通过 JSON-RPC over stdio 通信。每个微信用户对话会创建一个独立的 ACP session，支持多轮上下文。

### 自定义存储

默认使用 `JsonFileStorage`（文件 `~/.wechat-agent-sdk/accounts.json`）。你可以实现 `AccountStorage` 抽象类来替换为 Redis、SQLite 等：

```python
from wechat_agent_sdk import AccountStorage

class RedisStorage(AccountStorage):
    async def load_token(self, account_id: str) -> str | None: ...
    async def save_token(self, account_id: str, token: str) -> None: ...
    async def load_cursor(self, account_id: str) -> str | None: ...
    async def save_cursor(self, account_id: str, cursor: str) -> None: ...

bot = WeChatBot(agent=my_agent, storage=RedisStorage())
```

## 支持的消息类型

### 接收（微信 → Agent）

| 类型 | `ChatRequest` 行为 |
|------|-------------------|
| 文本 | `text` 字段直接拿到文字 |
| 图片 | `text` 为 `"[图片]"`，`media` 包含下载后的本地路径 |
| 语音 | 若有转写则 `text` 为转写文字，否则 `text` 为 `"[语音]"` |
| 视频 | `text` 为 `"[视频]"` |
| 文件 | `text` 为 `"[文件: xxx.pdf]"` |
| 引用消息 | 引用文本拼入 `text`，如 `"[引用: 原文] 新消息"` |

### 发送（Agent → 微信）

| 类型 | 用法 |
|------|------|
| 文本 | `ChatResponse(text="...")` |
| 长文本 | 自动按段落拆分（每段最长 4000 字符） |
| Markdown | 自动转纯文本（去掉 `**`、`#`、代码围栏等） |
| 图片 | `ChatResponse(media=MediaResponseInfo(type="image", url="..."))` (规划中) |

## 技术细节

- 使用 **长轮询** (`getUpdates`) 接收消息，无需公网服务器
- 消息去重：基于 `message_id` 的 OrderedDict 滑动窗口（1000 条）
- Typing 指示器：发送前自动显示"正在输入"，完成后取消
- Typing ticket 缓存：24 小时 TTL
- 错误重试：最多连续 3 次失败后 30 秒冷却
- 会话过期：`errcode -14` 触发 1 小时冷却后自动恢复
- 状态持久化：token 和 cursor 定期保存（5 秒间隔）

## 项目结构

```
src/wechat_agent_sdk/
├── __init__.py              # 公共 API 导出
├── agent.py                 # Agent 抽象基类
├── types.py                 # ChatRequest, ChatResponse, MediaInfo
├── api/
│   ├── client.py            # ILinkBotClient (5 个 API 端点)
│   ├── auth.py              # QR 扫码登录流程
│   └── types.py             # iLink API 数据模型
├── messaging/
│   ├── process.py           # 入站消息解析
│   ├── send.py              # 出站发送 + markdown 转换 + 长文本拆分
│   └── monitor.py           # 长轮询消息循环
├── acp/
│   └── adapter.py           # AcpAgent: ACP 子进程桥接适配器
├── account/
│   ├── manager.py           # WeChatBot: 账户生命周期编排
│   └── storage.py           # AccountStorage ABC + JsonFileStorage
└── utils/
    └── markdown.py          # strip_markdown()
```

## Roadmap

- [x] 单账户单聊（文本）
- [x] ACP 协议适配器
- [ ] 媒体消息收发（图片/视频/文件）
- [ ] 群聊支持（@Bot 过滤）
- [ ] 多账户管理
- [ ] Go SDK
- [ ] Node.js SDK

## 致谢

- [wong2/weixin-agent-sdk](https://github.com/wong2/weixin-agent-sdk) — 架构设计参考
- [m1heng/claude-plugin-weixin](https://github.com/m1heng/claude-plugin-weixin) — Claude 集成参考
- [Agent Client Protocol](https://agentclientprotocol.com/) — ACP 协议规范

## License

MIT
