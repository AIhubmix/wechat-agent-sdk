"""
WeChat Transport — transport layer, no Agent logic.

Standalone developers use ``WeChatBot`` (which calls Transport internally).
Platform integrators use ``WeChatTransport`` directly.

Usage (platform integration)::

    transport = WeChatTransport(account_id="bot_1", storage=my_storage)

    # Login
    session = await transport.request_login()
    result = await transport.check_login(session)

    # Receive messages
    await transport.connect()
    async for raw_msg in transport.messages():
        parsed = transport.parse(raw_msg)
        reply = await my_pipeline.handle(parsed)
        await transport.send_text(parsed.conversation_id, reply, parsed.context_token)

    await transport.disconnect()
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

from .api.auth import (
    LoginResult,
    LoginSession,
    LoginStatus,
    check_login as auth_check_login,
    login_with_qrcode,
    request_login as auth_request_login,
)
from .api.client import DEFAULT_API_BASE, ILinkBotClient, SessionExpiredError
from .account.storage import AccountStorage, JsonFileStorage
from .media.cdn import download_media as cdn_download, upload_media as cdn_upload
from .messaging.process import _extract_text, extract_all_media
from .messaging.send import split_text, MAX_MESSAGE_LENGTH
from .types import MediaInfo
from .utils.markdown import strip_markdown
from .api.types import WeixinMessage

logger = logging.getLogger(__name__)


@dataclass
class ParsedMessage:
    """Parsed message from iLink — transport-layer concept."""

    conversation_id: str
    text: str
    message_id: str = ""
    media: list[MediaInfo] = field(default_factory=list)
    group_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    is_at_bot: bool = False
    context_token: str = ""
    raw: Optional[dict] = None


class LoginRequiredError(Exception):
    """Raised when an operation requires a valid token but none is available."""


class WeChatTransport:
    """
    WeChat transport layer — connect, receive, parse, send.

    Does not manage Agents, middleware, or sessions.
    """

    def __init__(
        self,
        account_id: str = "default",
        storage: Optional[AccountStorage] = None,
        token: str = "",
        api_base_url: str = "",
    ):
        self._account_id = account_id
        self._storage = storage or JsonFileStorage()
        self._client = ILinkBotClient(
            token=token,
            base_url=api_base_url or DEFAULT_API_BASE,
        )
        self._cursor: str = ""
        self._running = False
        self._seen_ids: OrderedDict[str, None] = OrderedDict()

        # Typing ticket cache: chat_id -> (ticket, fetched_at)
        self._typing_tickets: dict[str, tuple[str, float]] = {}
        self._typing_ticket_ttl = 86400.0  # 24h

    # ── Properties ──

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def is_connected(self) -> bool:
        return self._running

    @property
    def client(self) -> ILinkBotClient:
        """Expose the underlying HTTP client for advanced use."""
        return self._client

    @property
    def needs_login(self) -> bool:
        """True when no valid token is available."""
        return not self._client.token

    # ── Token Management ──

    async def activate_token(self, token: str) -> None:
        """
        Inject a new token (e.g. after platform handles re-login).

        Persists the token to storage and updates the HTTP client.
        """
        self._client.token = token
        await self._storage.save_token(self._account_id, token)

    # ── Login ──

    async def login_terminal(self, log: callable = print) -> str:
        """Interactive terminal QR-code login. Returns the token."""
        stored = await self._storage.load_token(self._account_id)
        if stored:
            self._client.token = stored
            log(f"[weixin] Using saved token (account={self._account_id})")
            return stored

        token = await login_with_qrcode(self._client, log=log)
        await self._storage.save_token(self._account_id, token)
        return token

    async def request_login(self) -> LoginSession:
        """Get a QR code URL for programmatic (web UI) login."""
        stored = await self._storage.load_token(self._account_id)
        if stored:
            self._client.token = stored
            return LoginSession(qr_url="", uuid="")
        return await auth_request_login(self._client)

    async def check_login(self, session: LoginSession) -> LoginResult:
        """Poll login status. Persist token + metadata on success."""
        result = await auth_check_login(self._client, session)
        if result.status == LoginStatus.CONFIRMED and result.token:
            self._client.token = result.token
            await self._storage.save_token(self._account_id, result.token)
            if result.base_url:
                self._client._base_url = result.base_url
            await self._storage.save_meta(self._account_id, {
                "bot_id": result.bot_id or "",
                "user_id": result.user_id or "",
                "base_url": result.base_url or "",
            })
        return result

    async def logout(self) -> None:
        """Clear token and disconnect (forces re-login)."""
        self._client.token = ""
        await self._storage.save_token(self._account_id, "")
        await self.disconnect()

    # ── Connection & Message Stream ──

    async def connect(self) -> None:
        """Load cursor from storage and prepare for polling."""
        if not self._client.token:
            raise LoginRequiredError("No token. Login first.")
        cursor = await self._storage.load_cursor(self._account_id)
        if cursor:
            self._cursor = cursor
        self._running = True

    async def disconnect(self) -> None:
        """Save cursor, close HTTP client and storage."""
        self._running = False
        if self._cursor:
            await self._storage.save_cursor(self._account_id, self._cursor)
        await self._client.close()
        await self._storage.close()

    async def messages(self) -> AsyncIterator[dict]:
        """
        Async iterator: long-poll for messages.

        Yields raw message dicts. Auto-deduplicates and persists cursor.
        Raises ``SessionExpiredError`` when the token expires (clears token first).
        """
        consecutive_failures = 0

        while self._running:
            try:
                msgs, new_cursor = await self._client.get_updates(self._cursor)

                if new_cursor and new_cursor != self._cursor:
                    self._cursor = new_cursor

                consecutive_failures = 0

                for raw_msg in msgs:
                    # Skip bot's own messages
                    if raw_msg.get("message_type") == 2:
                        continue

                    # Dedup
                    msg_id = str(raw_msg.get("message_id", ""))
                    if msg_id and msg_id in self._seen_ids:
                        continue
                    if msg_id:
                        self._seen_ids[msg_id] = None
                        while len(self._seen_ids) > 1000:
                            self._seen_ids.popitem(last=False)

                    yield raw_msg

                # Persist cursor periodically
                if self._cursor:
                    await self._storage.save_cursor(self._account_id, self._cursor)

            except asyncio.CancelledError:
                break
            except SessionExpiredError:
                # Clear token so needs_login becomes True
                self._client.token = ""
                await self._storage.save_token(self._account_id, "")
                raise
            except Exception as e:
                consecutive_failures += 1
                logger.error(
                    f"Poll error ({consecutive_failures}/3): {e}"
                )
                if consecutive_failures >= 3:
                    consecutive_failures = 0
                    await asyncio.sleep(30.0)
                else:
                    await asyncio.sleep(2.0)

    # ── Parsing ──

    def parse(self, raw_msg: dict) -> Optional[ParsedMessage]:
        """Parse a raw iLink message dict into a ParsedMessage."""
        msg = WeixinMessage.from_dict(raw_msg)

        # Skip bot's own messages
        if msg.message_type == 2:
            return None

        # Skip empty messages
        if not msg.item_list and not msg.from_user_id:
            return None

        text = _extract_text(msg.item_list)
        media_list = extract_all_media(msg.item_list)
        context_token = raw_msg.get("context_token", "")

        return ParsedMessage(
            conversation_id=msg.from_user_id,
            text=text,
            message_id=str(msg.message_id) if msg.message_id else "",
            media=media_list,
            group_id=raw_msg.get("group_id") or None,
            sender_id=raw_msg.get("sender_id") or None,
            sender_name=raw_msg.get("sender_name") or None,
            is_at_bot=bool(raw_msg.get("is_at_bot")),
            context_token=context_token,
            raw=raw_msg,
        )

    # ── Sending ──

    async def send_text(
        self,
        chat_id: str,
        text: str,
        context_token: str = "",
    ) -> None:
        """Send text with auto markdown stripping and long-text splitting."""
        plain = strip_markdown(text)
        for chunk in split_text(plain, MAX_MESSAGE_LENGTH):
            await self._client.send_message(chat_id, chunk, context_token)

    async def send_text_raw(
        self,
        chat_id: str,
        text: str,
        context_token: str = "",
    ) -> None:
        """Send raw text without markdown processing or splitting."""
        await self._client.send_message(chat_id, text, context_token)

    async def send_media(
        self,
        chat_id: str,
        file_data: bytes,
        media_type: str,
        file_name: str = "",
        context_token: str = "",
    ) -> None:
        """Encrypt, upload to CDN, and send a media message."""
        type_map = {"image": 1, "video": 2, "file": 3, "voice": 4}
        media_type_int = type_map.get(media_type, 3)

        http_client = await self._client._ensure_client()
        cdn_info = await cdn_upload(
            bot_client=self._client,
            http_client=http_client,
            to_user_id=chat_id,
            file_data=file_data,
            media_type=media_type_int,
            file_name=file_name,
        )

        item = _build_media_item(media_type, cdn_info, file_name)
        await self._client.send_media_message(chat_id, item, context_token)

    async def download_media(self, media: MediaInfo) -> bytes:
        """Download and decrypt a media attachment."""
        http_client = await self._client._ensure_client()
        return await cdn_download(
            http_client, media.cdn_param, media.aes_key, media.aeskey_hex
        )

    # ── Typing Indicator ──

    async def send_typing(
        self,
        chat_id: str,
        start: bool = True,
        context_token: str = "",
    ) -> None:
        """Send typing indicator with auto ticket caching (24h TTL)."""
        ticket = await self._get_typing_ticket(chat_id, context_token)
        if ticket:
            await self._client.send_typing(chat_id, ticket, start=start)

    async def _get_typing_ticket(
        self,
        chat_id: str,
        context_token: str = "",
    ) -> Optional[str]:
        cached = self._typing_tickets.get(chat_id)
        if cached:
            ticket, fetched_at = cached
            if time.time() - fetched_at < self._typing_ticket_ttl:
                return ticket

        try:
            data = await self._client.get_config(chat_id, context_token)
            ticket = data.get("typing_ticket") or data.get("typingTicket")
            if ticket:
                self._typing_tickets[chat_id] = (ticket, time.time())
                return ticket
        except Exception:
            pass
        return None

    # ── Utilities ──

    @staticmethod
    def format_text(markdown: str) -> str:
        """Convert markdown to plain text for WeChat."""
        return strip_markdown(markdown)


def _build_media_item(media_type: str, cdn_info: dict, file_name: str = "") -> dict:
    """Build an item_list entry for sendmessage from CDN upload result."""
    media_ref = {
        "encrypt_query_param": cdn_info["encrypt_query_param"],
        "aes_key": cdn_info["aes_key"],
        "encrypt_type": cdn_info.get("encrypt_type", 1),
    }

    type_map = {"image": 2, "video": 5, "file": 4, "voice": 3}
    item_type = type_map.get(media_type, 4)

    if media_type == "image":
        return {"type": item_type, "image_item": {"media": media_ref}}
    elif media_type == "video":
        return {"type": item_type, "video_item": {"media": media_ref}}
    elif media_type == "voice":
        return {"type": item_type, "voice_item": {"media": media_ref}}
    else:
        item = {"type": item_type, "file_item": {"media": media_ref}}
        if file_name:
            item["file_item"]["file_name"] = file_name
        return item
