"""Core data types for wechat-agent-sdk."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MediaInfo:
    """Attachment (image, audio, video, or file)."""

    type: str  # "image" | "audio" | "video" | "file"

    # CDN reference (for lazy download via transport.download_media)
    cdn_param: str = ""  # encrypt_query_param
    aes_key: str = ""  # base64-encoded AES key (media.aes_key)
    aeskey_hex: str = ""  # hex AES key (image_item.aeskey, takes priority)

    # Local file info (populated after download)
    file_path: str = ""
    mime_type: str = "application/octet-stream"
    file_name: Optional[str] = None


@dataclass
class ChatRequest:
    """Inbound message from a WeChat user."""

    conversation_id: str  # User wxid (DM) or group id (group chat)
    text: str  # Text content of the message

    media: Optional[MediaInfo] = None  # Attached media file
    message_id: str = ""  # Unique message ID from iLink

    # Group chat fields (Phase 2)
    group_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    is_at_bot: bool = False

    # Raw iLink message for advanced use
    raw: Optional[dict] = None


@dataclass
class MediaResponseInfo:
    """Media attachment in a response."""

    type: str  # "image" | "video" | "file"
    url: str  # Local file path or HTTPS URL
    file_name: Optional[str] = None


@dataclass
class ChatResponse:
    """Reply from an Agent back to WeChat."""

    text: Optional[str] = None  # Reply text (markdown OK, auto-stripped before sending)

    media: Optional[MediaResponseInfo] = None  # Reply media
