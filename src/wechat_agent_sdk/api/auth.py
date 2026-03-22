"""QR code login flow for WeChat iLink Bot."""

from __future__ import annotations

import asyncio
import logging
import time

from .client import ILinkBotClient

logger = logging.getLogger(__name__)


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
    qr_info = await client.request_qrcode()
    qrcode_url = qr_info["qrcode_url"]
    qr_uuid = qr_info["uuid"]

    log("\n使用微信扫描以下二维码，以完成连接：\n")

    # Try terminal QR rendering
    try:
        import qrcode as qr_lib

        qr = qr_lib.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.print_ascii(invert=True)
    except ImportError:
        log(f"二维码链接: {qrcode_url}")
        log("(安装 qrcode 包可在终端显示二维码: pip install 'wechat-agent-sdk[qr]')")

    log("\n等待扫码...\n")

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        await asyncio.sleep(2.0)
        result = await client.check_login_status(qr_uuid)

        status = result["status"]
        if status == "confirmed":
            token = result["token"]
            client.token = token
            log("\n✅ 与微信连接成功！")
            return token
        elif status == "scanned":
            log("已扫码，请在手机上确认...")
        elif status == "expired":
            raise RuntimeError("二维码已过期，请重试")
        elif status == "error":
            raise RuntimeError(f"登录失败: {result.get('message', 'unknown error')}")
        # pending → continue

    raise RuntimeError(f"登录超时 ({timeout_seconds}s)")
