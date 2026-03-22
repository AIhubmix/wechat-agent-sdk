"""iLink Bot API request/response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# Message item types from iLink
class ItemType:
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


@dataclass
class MessageItem:
    """A single content item within a WeChat message."""

    type: int
    text_item: Optional[dict] = None
    image_item: Optional[dict] = None
    voice_item: Optional[dict] = None
    file_item: Optional[dict] = None
    video_item: Optional[dict] = None
    ref_msg: Optional[dict] = None  # Quoted/referenced message


@dataclass
class WeixinMessage:
    """A complete inbound message from iLink getUpdates."""

    from_user_id: str = ""
    to_user_id: str = ""
    message_id: str = ""
    message_type: int = 0  # 1=user, 2=bot
    context_token: str = ""
    create_time_ms: int = 0
    item_list: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> WeixinMessage:
        return cls(
            from_user_id=data.get("from_user_id", ""),
            to_user_id=data.get("to_user_id", ""),
            message_id=data.get("message_id") or data.get("msg_id") or "",
            message_type=data.get("message_type", 0),
            context_token=data.get("context_token", ""),
            create_time_ms=data.get("create_time_ms", 0),
            item_list=data.get("item_list", []),
            raw=data,
        )
