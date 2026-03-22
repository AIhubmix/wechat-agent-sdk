"""
ACP Agent 示例 — 通过 ACP 协议接入 Claude Code、Codex、Kimi 等 Agent。

Usage:
    # 接入 Claude Code
    python examples/acp_bot.py claude-agent-acp

    # 接入 Codex
    python examples/acp_bot.py codex-acp

    # 接入 Kimi CLI
    python examples/acp_bot.py kimi acp
"""

import asyncio
import sys

from wechat_agent_sdk import WeChatBot
from wechat_agent_sdk.acp.adapter import AcpAgent


def parse_command(argv: list[str]) -> tuple[str, list[str]]:
    """Parse command and args from argv."""
    if len(argv) < 2:
        print("Usage: python examples/acp_bot.py <command> [args...]")
        print()
        print("Examples:")
        print("  python examples/acp_bot.py claude-agent-acp")
        print("  python examples/acp_bot.py codex-acp")
        print("  python examples/acp_bot.py kimi acp")
        sys.exit(1)

    command = argv[1]
    args = argv[2:]
    return command, args


async def main():
    command, args = parse_command(sys.argv)

    agent = AcpAgent(command=command, args=args)
    bot = WeChatBot(agent=agent)

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
