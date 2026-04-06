"""QR code login flow for WeChat iLink Bot."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .client import ILinkBotClient

logger = logging.getLogger(__name__)


# ── Web Login API types ──


class LoginStatus(str, Enum):
    """QR login status."""

    PENDING = "pending"
    SCANNED = "scanned"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class LoginSession:
    """QR code session for programmatic login."""

    qr_url: str
    uuid: str


@dataclass
class LoginResult:
    """Result of a login status poll."""

    status: LoginStatus
    token: Optional[str] = None
    bot_id: Optional[str] = None
    user_id: Optional[str] = None
    base_url: Optional[str] = None
    error: Optional[str] = None


# ── Low-level login functions (for Web UI integration) ──


async def request_login(client: ILinkBotClient) -> LoginSession:
    """Request a QR code URL for programmatic login."""
    qr_info = await client.request_qrcode()
    return LoginSession(
        qr_url=qr_info["qrcode_url"],
        uuid=qr_info["uuid"],
    )


async def check_login(client: ILinkBotClient, session: LoginSession) -> LoginResult:
    """Poll login status. Returns a typed LoginResult."""
    result = await client.check_login_status(session.uuid)
    status_str = result.get("status", "pending")

    try:
        status = LoginStatus(status_str)
    except ValueError:
        status = LoginStatus.PENDING

    return LoginResult(
        status=status,
        token=result.get("token"),
        bot_id=result.get("bot_id"),
        user_id=result.get("user_id"),
        base_url=result.get("base_url"),
        error=result.get("message"),
    )


# ── Terminal login (interactive) ──


async def login_with_qrcode(
    client: ILinkBotClient,
    log: callable = print,
    timeout_seconds: int = 120,
) -> str:
    """
    Interactive QR-code login via terminal.

    Prints the QR code, waits for the user to scan, and returns the token.
    Raises RuntimeError on failure/timeout.
    """
    session = await request_login(client)

    log("\n使用微信扫描以下二维码，以完成连接：\n")

    try:
        import qrcode as qr_lib

        qr = qr_lib.QRCode(border=1)
        qr.add_data(session.qr_url)
        qr.print_ascii(invert=True)
    except ImportError:
        log(f"二维码链接: {session.qr_url}")
        log("(安装 qrcode 包可在终端显示二维码: pip install 'wechat-agent-sdk[qr]')")

    log("\n等待扫码...\n")

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        await asyncio.sleep(2.0)
        result = await check_login(client, session)

        if result.status == LoginStatus.CONFIRMED:
            client.token = result.token
            log("\n✅ 与微信连接成功！")
            return result.token
        elif result.status == LoginStatus.SCANNED:
            log("已扫码，请在手机上确认...")
        elif result.status == LoginStatus.EXPIRED:
            raise RuntimeError("二维码已过期，请重试")
        elif result.status == LoginStatus.ERROR:
            raise RuntimeError(f"登录失败: {result.error or 'unknown error'}")

    raise RuntimeError(f"登录超时 ({timeout_seconds}s)")
