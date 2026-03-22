"""Parse inbound iLink messages into ChatRequest."""

from __future__ import annotations

import logging
from typing import Optional

from ..api.types import ItemType, WeixinMessage
from ..types import ChatRequest

logger = logging.getLogger(__name__)


def parse_message(raw: dict) -> Optional[ChatRequest]:
    """
    Parse a raw iLink message dict into a ChatRequest.

    Returns None if the message should be skipped (e.g., bot's own messages).
    """
    msg = WeixinMessage.from_dict(raw)

    # Skip bot's own messages (message_type=2 is BOT)
    if msg.message_type == 2:
        return None

    # Skip empty messages
    if not msg.item_list and not msg.from_user_id:
        return None

    text = _extract_text(msg.item_list)

    return ChatRequest(
        conversation_id=msg.from_user_id,
        text=text,
        message_id=msg.message_id,
        raw=raw,
    )


def _extract_text(item_list: list[dict]) -> str:
    """Extract text content from item_list."""
    parts: list[str] = []

    for item in item_list:
        item_type = item.get("type", 0)

        if item_type == ItemType.TEXT:
            text_item = item.get("text_item", {})
            text = text_item.get("text", "")
            if text:
                parts.append(text)

            # Handle quoted/referenced message text
            ref_msg = item.get("ref_msg")
            if ref_msg:
                ref_item = ref_msg.get("message_item", {})
                ref_text = _extract_text_from_item(ref_item)
                if ref_text:
                    parts.append(f"[引用: {ref_text}]")

        elif item_type == ItemType.VOICE:
            voice_item = item.get("voice_item", {})
            # Voice-to-text transcription
            voice_text = voice_item.get("text", "")
            if voice_text:
                parts.append(voice_text)
            else:
                parts.append("[语音]")

        elif item_type == ItemType.IMAGE:
            if not parts or parts[-1] != "[图片]":
                parts.append("[图片]")

        elif item_type == ItemType.VIDEO:
            parts.append("[视频]")

        elif item_type == ItemType.FILE:
            file_item = item.get("file_item", {})
            file_name = file_item.get("file_name", "")
            parts.append(f"[文件: {file_name}]" if file_name else "[文件]")

    return " ".join(parts) if parts else ""


def _extract_text_from_item(item: dict) -> str:
    """Extract text from a single message item (used for ref_msg)."""
    item_type = item.get("type", 0)
    if item_type == ItemType.TEXT:
        return item.get("text_item", {}).get("text", "")
    return ""
