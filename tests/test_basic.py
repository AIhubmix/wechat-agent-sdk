"""Basic import and functionality tests."""

from wechat_agent_sdk import Agent, ChatRequest, ChatResponse, WeChatBot, JsonFileStorage
from wechat_agent_sdk.acp.adapter import AcpAgent
from wechat_agent_sdk.utils.markdown import strip_markdown
from wechat_agent_sdk.api.client import ILinkBotClient
from wechat_agent_sdk.messaging.process import parse_message
from wechat_agent_sdk.messaging.send import split_text


def test_imports():
    """All public classes are importable."""
    assert Agent is not None
    assert ChatRequest is not None
    assert ChatResponse is not None
    assert WeChatBot is not None
    assert AcpAgent is not None
    assert JsonFileStorage is not None


def test_strip_markdown():
    assert strip_markdown("**bold**") == "bold"
    assert strip_markdown("_italic_") == "italic"
    assert strip_markdown("`code`") == "code"
    assert strip_markdown("# Header") == "Header"
    assert strip_markdown("[link](http://example.com)") == "link (http://example.com)"
    assert strip_markdown("![alt](http://img.png)") == "[图片: alt]"
    assert strip_markdown("~~strike~~") == "strike"
    assert strip_markdown("---") == "————"
    assert strip_markdown("") == ""
    assert strip_markdown("plain text") == "plain text"

    # Combined
    result = strip_markdown("**Hello** _world_ `code`")
    assert result == "Hello world code"


def test_split_text():
    # Short text — no split
    assert split_text("hello") == ["hello"]

    # Long text — force split
    long_text = "a" * 5000
    chunks = split_text(long_text, max_length=4000)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4000
    assert len(chunks[1]) == 1000

    # Split at paragraph boundary
    text = ("A" * 2000) + "\n\n" + ("B" * 2000) + "\n\n" + ("C" * 2000)
    chunks = split_text(text, max_length=4500)
    assert len(chunks) == 2


def test_parse_message_text():
    msg = parse_message({
        "from_user_id": "wxid_test",
        "message_type": 1,
        "message_id": "msg123",
        "context_token": "ctx456",
        "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
    })
    assert msg is not None
    assert msg.conversation_id == "wxid_test"
    assert msg.text == "hello"
    assert msg.message_id == "msg123"


def test_parse_message_filters_bot():
    """Bot messages (message_type=2) should be filtered."""
    msg = parse_message({
        "from_user_id": "wxid_test",
        "message_type": 2,
        "item_list": [{"type": 1, "text_item": {"text": "bot reply"}}],
    })
    assert msg is None


def test_parse_message_voice_transcription():
    msg = parse_message({
        "from_user_id": "wxid_test",
        "message_type": 1,
        "item_list": [{"type": 3, "voice_item": {"text": "voice transcribed text"}}],
    })
    assert msg is not None
    assert msg.text == "voice transcribed text"


def test_parse_message_empty():
    msg = parse_message({
        "from_user_id": "",
        "message_type": 0,
        "item_list": [],
    })
    assert msg is None
