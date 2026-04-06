"""
Transport 层独立使用示例 — 平台集成场景。

Transport 层不管 Agent、不管中间件，只做传输：
连接、收消息、解析、发送。

平台自己管权限、会话、Agent 调用、SSE 流式。

Usage:
    python examples/transport_demo.py
"""

import asyncio

from wechat_agent_sdk import WeChatTransport


async def main():
    transport = WeChatTransport(account_id="demo")

    # Terminal login (or use request_login() + check_login() for web UI)
    await transport.login_terminal()

    # Connect and receive messages
    await transport.connect()
    print("[transport] Connected, waiting for messages...")

    try:
        async for raw_msg in transport.messages():
            parsed = transport.parse(raw_msg)
            if not parsed:
                continue

            print(f"[transport] From: {parsed.conversation_id}")
            print(f"[transport] Text: {parsed.text}")
            print(f"[transport] Media count: {len(parsed.media)}")

            # Echo reply via transport
            await transport.send_text(
                parsed.conversation_id,
                f"[Transport 模式] 收到: {parsed.text}",
                parsed.context_token,
            )
    except KeyboardInterrupt:
        pass
    finally:
        await transport.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
