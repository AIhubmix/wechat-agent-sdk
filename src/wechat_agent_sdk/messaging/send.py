"""Outbound message sending pipeline."""

from __future__ import annotations

import logging

from ..api.client import ILinkBotClient
from ..types import ChatResponse
from ..utils.markdown import strip_markdown

logger = logging.getLogger(__name__)

# WeChat text message length limit (~2000 chars per iLink protocol)
MAX_MESSAGE_LENGTH = 2000


async def send_response(
    client: ILinkBotClient,
    to_user_id: str,
    response: ChatResponse,
    context_token: str = "",
) -> None:
    """Send a ChatResponse to a WeChat user."""
    if response.text:
        plain_text = strip_markdown(response.text)
        # Split long messages
        for chunk in split_text(plain_text, MAX_MESSAGE_LENGTH):
            await client.send_message(to_user_id, chunk, context_token)

    if response.media:
        logger.warning(
            "send_response() does not support media upload. "
            "Use WeChatTransport.send_media() for full media support."
        )


def split_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split long text into chunks at paragraph boundaries."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at paragraph boundary
        split_pos = remaining.rfind("\n\n", 0, max_length)
        if split_pos == -1:
            # Try single newline
            split_pos = remaining.rfind("\n", 0, max_length)
        if split_pos == -1:
            # Force split at max_length
            split_pos = max_length

        chunks.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()

    return chunks
