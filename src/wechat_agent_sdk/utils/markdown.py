"""Markdown to plain text converter for WeChat."""

from __future__ import annotations

import re


def strip_markdown(text: str) -> str:
    """
    Convert markdown to WeChat-friendly plain text.

    WeChat does not render markdown, so we strip formatting while
    preserving readability.
    """
    if not text:
        return text

    # Code blocks: ```lang\ncode\n``` → keep code content, remove fences
    text = re.sub(r"```\w*\n(.*?)```", r"\1", text, flags=re.DOTALL)

    # Inline code: `code` → code
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Images: ![alt](url) → [图片: alt]
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"[图片: \1]", text)

    # Links: [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Headers: ### text → text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Bold: **text** or __text__ → text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)

    # Italic: *text* or _text_ → text
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"\1", text)

    # Strikethrough: ~~text~~ → text
    text = re.sub(r"~~(.+?)~~", r"\1", text)

    # Horizontal rules: --- or *** → ————
    text = re.sub(r"^[-*_]{3,}\s*$", "————", text, flags=re.MULTILINE)

    return text.strip()
