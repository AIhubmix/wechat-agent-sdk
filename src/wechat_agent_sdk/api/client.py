"""iLink Bot HTTP API client."""

from __future__ import annotations

import base64
import json
import logging
import random
import uuid as uuid_lib
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# iLink Bot API base URL
DEFAULT_API_BASE = "https://ilinkai.weixin.qq.com"

# Long-poll timeout (seconds) — server holds request up to this duration
POLL_TIMEOUT = 35

CHANNEL_VERSION = "1.0.2"


def _make_wechat_uin() -> str:
    """Generate X-WECHAT-UIN header value: base64(str(random_uint32))."""
    return base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()


class ILinkBotClient:
    """Async HTTP client for the WeChat iLink Bot API."""

    def __init__(
        self,
        token: str = "",
        base_url: str = DEFAULT_API_BASE,
    ):
        self._token = token
        self._base_url = base_url
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        self._token = value
        if self._client:
            self._client.headers["Authorization"] = f"Bearer {value}"

    async def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=POLL_TIMEOUT + 10,
                    write=10.0,
                    pool=10.0,
                ),
                headers={
                    "Content-Type": "application/json",
                    "AuthorizationType": "ilink_bot_token",
                },
                event_hooks={"request": [self._inject_uin_header]},
            )
            if self._token:
                self._client.headers["Authorization"] = f"Bearer {self._token}"
        return self._client

    @staticmethod
    async def _inject_uin_header(request: httpx.Request) -> None:
        """Inject a fresh X-WECHAT-UIN on every request."""
        request.headers["X-WECHAT-UIN"] = _make_wechat_uin()

    def _base_info(self) -> dict:
        return {"channel_version": CHANNEL_VERSION}

    # ------------------------------------------------------------------
    # getUpdates — long-poll for new messages
    # ------------------------------------------------------------------

    async def get_updates(self, cursor: str = "") -> tuple[list[dict], str]:
        """
        Long-poll for new messages.

        Returns (messages, new_cursor). On timeout returns ([], cursor).
        """
        client = await self._ensure_client()

        payload = {
            "get_updates_buf": cursor,
            "base_info": self._base_info(),
        }

        try:
            resp = await client.post(
                f"{self._base_url}/ilink/bot/getupdates",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            return [], cursor

        new_cursor = data.get("get_updates_buf") or cursor
        msgs = data.get("msgs") or []

        # Track server-suggested poll timeout
        suggested_timeout = data.get("longpolling_timeout_ms")
        if suggested_timeout:
            self._suggested_poll_timeout = suggested_timeout / 1000

        # Check for API errors
        ret = data.get("ret", 0)
        errcode = data.get("errcode", 0)
        if ret != 0 or errcode != 0:
            errmsg = data.get("errmsg", "")
            logger.warning(f"getUpdates error: ret={ret} errcode={errcode} errmsg={errmsg}")
            # Session expired
            if errcode == -14 or ret == -14:
                raise SessionExpiredError(f"Session expired (errcode={errcode})")

        return msgs, new_cursor

    # ------------------------------------------------------------------
    # sendMessage — send a text reply
    # ------------------------------------------------------------------

    async def send_message(
        self,
        to_user_id: str,
        text: str,
        context_token: str = "",
    ) -> None:
        """Send a text message via iLink Bot API."""
        client = await self._ensure_client()

        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"wechat-agent-sdk-{uuid_lib.uuid4().hex[:16]}",
                "message_type": 2,  # BOT message
                "message_state": 2,  # FINISH (complete message)
                "item_list": [
                    {"type": 1, "text_item": {"text": text}},
                ],
                "context_token": context_token,
            },
            "base_info": self._base_info(),
        }

        resp = await client.post(
            f"{self._base_url}/ilink/bot/sendmessage",
            json=payload,
            timeout=10.0,
        )
        raw = resp.text
        if raw.strip():
            result = resp.json()
            ret = result.get("ret")
            if ret is not None and ret != 0:
                logger.error(f"sendMessage failed: {result}")

    # ------------------------------------------------------------------
    # sendTyping — typing indicator
    # ------------------------------------------------------------------

    async def send_typing(self, to_user_id: str, ticket: str, start: bool = True) -> None:
        """Send typing indicator. Raises on non-2xx so caller can invalidate ticket."""
        client = await self._ensure_client()

        resp = await client.post(
            f"{self._base_url}/ilink/bot/sendtyping",
            json={
                "ilink_user_id": to_user_id,
                "typing_ticket": ticket,
                "status": 1 if start else 2,
                "base_info": self._base_info(),
            },
            timeout=5.0,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # getConfig — get typing ticket for a user
    # ------------------------------------------------------------------

    async def get_config(
        self,
        to_user_id: str,
        context_token: str = "",
    ) -> dict:
        """Fetch bot config (typing_ticket) for a given user."""
        client = await self._ensure_client()

        try:
            resp = await client.post(
                f"{self._base_url}/ilink/bot/getconfig",
                json={
                    "ilink_user_id": to_user_id,
                    "context_token": context_token,
                    "base_info": self._base_info(),
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"getConfig failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # getUploadUrl — CDN media upload pre-signed URL
    # ------------------------------------------------------------------

    async def get_upload_url(
        self,
        filekey: str,
        media_type: int,
        to_user_id: str,
        raw_size: int,
        raw_file_md5: str,
        file_size: int,
        aes_key_hex: str,
        no_need_thumb: bool = True,
    ) -> dict:
        """Get a CDN pre-signed upload URL via /ilink/bot/getuploadurl."""
        client = await self._ensure_client()

        resp = await client.post(
            f"{self._base_url}/ilink/bot/getuploadurl",
            json={
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": raw_size,
                "rawfilemd5": raw_file_md5,
                "filesize": file_size,
                "aeskey": aes_key_hex,
                "no_need_thumb": no_need_thumb,
                "base_info": self._base_info(),
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # sendMessage — send a media message (pre-built item)
    # ------------------------------------------------------------------

    async def send_media_message(
        self,
        to_user_id: str,
        item: dict,
        context_token: str = "",
    ) -> None:
        """Send a message with a pre-built media item_list entry."""
        client = await self._ensure_client()

        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"wechat-agent-sdk-{uuid_lib.uuid4().hex[:16]}",
                "message_type": 2,
                "message_state": 2,
                "item_list": [item],
                "context_token": context_token,
            },
            "base_info": self._base_info(),
        }

        resp = await client.post(
            f"{self._base_url}/ilink/bot/sendmessage",
            json=payload,
            timeout=30.0,
        )
        raw = resp.text
        if raw.strip():
            result = resp.json()
            ret = result.get("ret")
            if ret is not None and ret != 0:
                logger.error(f"sendMediaMessage failed: {result}")

    # ------------------------------------------------------------------
    # QR Login endpoints
    # ------------------------------------------------------------------

    async def request_qrcode(self) -> dict:
        """
        Request a QR code for login.

        Returns {"qrcode_url": str, "uuid": str} on success.
        Raises on failure.
        """
        client = await self._ensure_client()

        resp = await client.get(
            f"{self._base_url}/ilink/bot/get_bot_qrcode",
            params={"bot_type": "3"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        qrcode_url = (
            data.get("qrcode_img_content")
            or data.get("qrcode_url")
            or data.get("qrcodeUrl")
        )
        qr_uuid = data.get("qrcode") or data.get("uuid")

        if not qrcode_url or not qr_uuid:
            raise ValueError(f"Failed to get QR code: {data}")

        return {"qrcode_url": qrcode_url, "uuid": qr_uuid}

    async def check_login_status(self, qr_uuid: str) -> dict:
        """
        Check QR code scan status.

        Returns dict with "status" key and optional "token", "bot_id",
        "user_id", "base_url" on confirmed login.
        """
        client = await self._ensure_client()

        try:
            resp = await client.get(
                f"{self._base_url}/ilink/bot/get_qrcode_status",
                params={"qrcode": qr_uuid},
                headers={"iLink-App-ClientVersion": "1"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.ReadTimeout:
            return {"status": "pending"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

        status = data.get("status", "")

        if status == "confirmed":
            token = data.get("bot_token", "")
            if not token:
                return {"status": "error", "message": "Confirmed but no token"}
            return {
                "status": "confirmed",
                "token": token,
                "bot_id": data.get("ilink_bot_id", ""),
                "user_id": data.get("ilink_user_id", ""),
                "base_url": data.get("baseurl", ""),
            }
        elif status == "scaned":  # iLink protocol spelling
            return {"status": "scanned"}
        elif status == "expired":
            return {"status": "expired"}
        else:
            return {"status": "pending"}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class SessionExpiredError(Exception):
    """Raised when the WeChat session has expired (errcode -14)."""
