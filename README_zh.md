# wechat-agent-sdk

[English](./README.md) | 中文

微信 AI Agent 桥接框架 — 通过简单的 Agent 接口，将任意 AI 后端接入微信。

支持 [ACP (Agent Client Protocol)](https://agentclientprotocol.com/) 协议，可直接接入 Claude Code、Codex、Kimi 等 Agent。

> 本项目非微信官方项目，基于 iLink Bot API，仅供学习交流使用。

## 工作原理

1. 安装本 SDK，创建一个 Python 脚本并实现 `Agent` 接口
2. SDK 自动处理微信登录（二维码）、消息轮询、去重和回复投递
3. 你只需实现一个方法：`chat(request) -> response`

## 安装

```bash
pip install wechat-agent-sdk
```

根据使用场景安装可选依赖：

```bash
# 终端二维码显示（推荐）
pip install 'wechat-agent-sdk[qr]'

# ACP 协议支持（接入 Claude Code / Codex / Kimi 时必须）
pip install 'wechat-agent-sdk[acp]'

# OpenAI 集成
pip install 'wechat-agent-sdk[openai]'
```

> 要求 Python >= 3.11

## 集成指南

> **Note for AI Agents**: 本文档面向 AI Agent（如 Claude Code）阅读。请按照下方的集成模式编写代码来实现微信接入，而不是直接运行 `examples/` 中的示例文件。`examples/` 仅作为代码模式参考。

要将 AI 后端接入微信，请创建一个 Python 脚本，按照以下模式实现：

### 第一步：实现 Agent 接口

继承 `Agent` 并实现 `chat()` 方法。这是唯一必须实现的方法。SDK 会对每条微信消息调用 `chat()`，并将返回的 `ChatResponse` 发送给用户。

```python
import asyncio
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot

class MyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        # request.text 包含用户消息
        # request.conversation_id 标识用户/对话
        # 返回 ChatResponse，包含回复文本
        return ChatResponse(text=f"你说了: {request.text}")

async def main():
    bot = WeChatBot(agent=MyAgent())
    await bot.run()

asyncio.run(main())
```

### 第二步：运行并登录

运行脚本后，终端会显示二维码（需安装 `qrcode` 依赖），用微信扫码登录。登录信息会保存到 `~/.wechat-agent-sdk/accounts.json`，下次启动自动复用。

---

## 集成模式

### 模式 A：通过 ACP 接入 Claude Code

使用此模式将 [Claude Code](https://code.claude.com/) 或其他 ACP 兼容 Agent 桥接到微信。

**前置准备：**

1. 安装对应 Agent 的 ACP 适配器（需要 Node.js >= 18）：

```bash
# Claude Code ACP 适配器
npm install -g @zed-industries/claude-code-acp
```

> 也可以从 [Releases 页面](https://github.com/zed-industries/claude-agent-acp/releases) 下载预编译二进制文件。

2. 安装 SDK 及 ACP 支持：

```bash
pip install 'wechat-agent-sdk[acp,qr]'
```

**实现代码：**

```python
import asyncio
from wechat_agent_sdk import WeChatBot
from wechat_agent_sdk.acp.adapter import AcpAgent

async def main():
    agent = AcpAgent(
        command="claude-agent-acp",       # ACP agent 启动命令
        permission_mode="bypassPermissions",  # 必须：跳过终端权限提示
    )
    bot = WeChatBot(agent=agent)
    await bot.run()

asyncio.run(main())
```

**支持的 ACP Agent：**

| Agent | 安装 | command | 参考 |
|-------|------|---------|------|
| Claude Code | `npm i -g @zed-industries/claude-code-acp` | `claude-agent-acp` | [zed-industries/claude-agent-acp](https://github.com/zed-industries/claude-agent-acp) |
| Codex | `npm i -g @openai/codex-acp` | `codex-acp` | [zed-industries/codex-acp](https://github.com/zed-industries/codex-acp) |
| Kimi CLI | `npm i -g kimi-cli` | `kimi` (args: `["acp"]`) | [moonshotai/kimi-cli](https://github.com/nicepkg/kimi-cli) |

```python
# Kimi CLI 示例
agent = AcpAgent(command="kimi", args=["acp"])
```

### 模式 B：OpenAI / 兼容 API

使用此模式接入 OpenAI，或任何兼容 OpenAI 接口的服务（如 DeepSeek、Moonshot、Ollama 本地模型）。

**前置准备：**

```bash
pip install 'wechat-agent-sdk[openai,qr]'
```

设置 `OPENAI_API_KEY` 环境变量。如使用兼容 API，可选设置 `OPENAI_BASE_URL`。

**实现代码：**

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

### 模式 C：自定义 Agent

实现任意自定义逻辑。`Agent` 接口设计为极简：

```python
from wechat_agent_sdk import Agent, ChatRequest, ChatResponse

class MyAgent(Agent):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """处理单条消息并返回回复。（必须实现）"""
        ...

    async def on_start(self) -> None:
        """Bot 启动时调用一次。用于初始化（如加载模型）。"""
        ...

    async def on_stop(self) -> None:
        """Bot 停止时调用一次。用于清理资源。"""
        ...
```

## API 参考

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

通过 ACP 协议桥接外部 Agent。**需先单独安装对应的 ACP 适配器**（见上方集成模式）。

```python
from wechat_agent_sdk.acp.adapter import AcpAgent

agent = AcpAgent(
    command="claude-agent-acp",           # ACP agent 启动命令
    args=[],                               # 命令参数
    cwd=None,                              # 工作目录（默认当前目录）
    env=None,                              # 额外环境变量
    auto_approve=True,                     # 自动批准 ACP 协议层的权限请求
    permission_mode="bypassPermissions",   # Agent 内部权限模式（见下方说明）
)
```

**权限模式** (`permission_mode`) — `claude-agent-acp` 等 ACP Agent 有独立于 ACP 协议的内部权限系统。在微信这种非交互环境下，Agent 无法弹出终端确认框，会直接回复"没有权限"。此参数通过设置 `ACP_PERMISSION_MODE` 环境变量来控制：

| 模式 | 行为 |
|------|------|
| `"bypassPermissions"` | 跳过所有权限提示（**默认，推荐用于微信场景**） |
| `"acceptEdits"` | 自动批准文件编辑，其他操作仍需确认 |
| `"default"` | 所有操作都需确认（在非交互环境下通常会失败） |

**流式输出** — 当 ACP Agent 执行工具调用（如读取文件、运行命令）时，已累积的文本会在每次工具调用前自动推送到微信，用户可以看到增量输出，无需等待整个响应完成。

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

## 致谢

- [wong2/weixin-agent-sdk](https://github.com/wong2/weixin-agent-sdk) — 架构设计参考
- [m1heng/claude-plugin-weixin](https://github.com/m1heng/claude-plugin-weixin) — Claude 集成参考
- [Agent Client Protocol](https://agentclientprotocol.com/) — ACP 协议规范

## License

MIT
