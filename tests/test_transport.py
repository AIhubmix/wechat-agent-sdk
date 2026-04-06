"""Test WeChatTransport layer."""

import asyncio
import pytest

from wechat_agent_sdk import WeChatTransport, ParsedMessage, LoginRequiredError
from wechat_agent_sdk.account.storage import JsonFileStorage
from wechat_agent_sdk.api.client import SessionExpiredError
from wechat_agent_sdk.types import MediaInfo


# ── Parsing tests ──


def _make_text_msg(text="hello", from_user="user_123", msg_id=1001):
    return {
        "from_user_id": from_user,
        "message_type": 1,
        "message_id": msg_id,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
        "context_token": "ctx_token_abc",
    }


def _make_image_msg(from_user="user_123", msg_id=1002):
    return {
        "from_user_id": from_user,
        "message_type": 1,
        "message_id": msg_id,
        "item_list": [
            {"type": 1, "text_item": {"text": "看这个"}},
            {
                "type": 2,
                "image_item": {
                    "media": {
                        "encrypt_query_param": "cdn_param_1",
                        "aes_key": "AAAAAAAAAAAAAAAAAAAAAA==",
                    },
                    "aeskey": "00112233445566778899aabbccddeeff",
                },
            },
            {
                "type": 2,
                "image_item": {
                    "media": {
                        "encrypt_query_param": "cdn_param_2",
                        "aes_key": "BBBBBBBBBBBBBBBBBBBBBB==",
                    },
                },
            },
        ],
        "context_token": "ctx_img",
    }


class TestTransportParse:
    def setup_method(self):
        self.transport = WeChatTransport(account_id="test")

    def test_parse_text_message(self):
        msg = _make_text_msg("你好")
        parsed = self.transport.parse(msg)

        assert parsed is not None
        assert parsed.conversation_id == "user_123"
        assert parsed.text == "你好"
        assert parsed.message_id == "1001"
        assert parsed.context_token == "ctx_token_abc"
        assert parsed.media == []

    def test_parse_bot_message_returns_none(self):
        msg = _make_text_msg()
        msg["message_type"] = 2
        assert self.transport.parse(msg) is None

    def test_parse_empty_message_returns_none(self):
        msg = {"message_type": 1, "item_list": [], "from_user_id": ""}
        assert self.transport.parse(msg) is None

    def test_parse_multi_media(self):
        """Gap 1: parse() should return all media items, not just the first."""
        msg = _make_image_msg()
        parsed = self.transport.parse(msg)

        assert parsed is not None
        assert parsed.text == "看这个 [图片] [图片]"
        assert len(parsed.media) == 2

        # First image has aeskey_hex priority
        assert parsed.media[0].type == "image"
        assert parsed.media[0].cdn_param == "cdn_param_1"
        assert parsed.media[0].aeskey_hex == "00112233445566778899aabbccddeeff"

        # Second image only has base64 key
        assert parsed.media[1].type == "image"
        assert parsed.media[1].cdn_param == "cdn_param_2"
        assert parsed.media[1].aeskey_hex == ""

    def test_parse_file_message(self):
        msg = {
            "from_user_id": "user_456",
            "message_type": 1,
            "message_id": 2001,
            "item_list": [
                {
                    "type": 4,
                    "file_item": {
                        "media": {"encrypt_query_param": "file_cdn", "aes_key": "key123"},
                        "file_name": "report.pdf",
                    },
                }
            ],
            "context_token": "ctx_file",
        }
        parsed = self.transport.parse(msg)
        assert parsed is not None
        assert len(parsed.media) == 1
        assert parsed.media[0].type == "file"
        assert parsed.media[0].file_name == "report.pdf"


# ── Token management tests ──


class TestTransportTokenManagement:
    @pytest.mark.asyncio
    async def test_needs_login_true_when_no_token(self):
        transport = WeChatTransport(account_id="test")
        assert transport.needs_login is True

    @pytest.mark.asyncio
    async def test_needs_login_false_when_token_set(self):
        transport = WeChatTransport(account_id="test", token="tok_123")
        assert transport.needs_login is False

    @pytest.mark.asyncio
    async def test_activate_token(self, tmp_path):
        storage = JsonFileStorage(state_dir=tmp_path)
        transport = WeChatTransport(account_id="bot1", storage=storage)

        assert transport.needs_login is True
        await transport.activate_token("new_tok")
        assert transport.needs_login is False
        assert transport.client.token == "new_tok"

        # Verify persisted
        assert await storage.load_token("bot1") == "new_tok"

    @pytest.mark.asyncio
    async def test_logout(self, tmp_path):
        storage = JsonFileStorage(state_dir=tmp_path)
        await storage.save_token("bot1", "old_tok")
        transport = WeChatTransport(account_id="bot1", storage=storage, token="old_tok")

        assert transport.needs_login is False
        await transport.logout()
        assert transport.needs_login is True
        assert transport.is_connected is False

        # Verify token cleared in storage (JsonFileStorage returns None for empty)
        stored = await storage.load_token("bot1")
        assert not stored

    @pytest.mark.asyncio
    async def test_connect_without_token_raises(self):
        transport = WeChatTransport(account_id="test")
        with pytest.raises(LoginRequiredError):
            await transport.connect()


# ── Message stream tests ──


class TestTransportMessages:
    @pytest.mark.asyncio
    async def test_session_expired_clears_token(self, tmp_path):
        """Gap 3: SessionExpiredError should auto-clear the token."""
        storage = JsonFileStorage(state_dir=tmp_path)
        await storage.save_token("bot1", "expired_tok")
        transport = WeChatTransport(account_id="bot1", storage=storage, token="expired_tok")
        await transport.connect()

        # Mock get_updates to raise SessionExpiredError
        async def fake_get_updates(cursor=""):
            raise SessionExpiredError("Session expired")

        transport.client.get_updates = fake_get_updates

        with pytest.raises(SessionExpiredError):
            async for _ in transport.messages():
                pass

        # Token should be cleared
        assert transport.needs_login is True
        stored = await storage.load_token("bot1")
        assert not stored

    @pytest.mark.asyncio
    async def test_dedup_in_messages(self, tmp_path):
        storage = JsonFileStorage(state_dir=tmp_path)
        await storage.save_token("bot1", "tok")
        transport = WeChatTransport(account_id="bot1", storage=storage, token="tok")
        await transport.connect()

        call_count = 0
        msg = _make_text_msg("hi", msg_id=999)

        async def fake_get_updates(cursor=""):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Return same message twice
                return [msg], "cursor_1"
            # Then stop
            transport._running = False
            return [], "cursor_1"

        transport.client.get_updates = fake_get_updates

        received = []
        async for raw in transport.messages():
            received.append(raw)

        # Should only get one copy despite being returned twice
        assert len(received) == 1


# ── Utility tests ──


class TestTransportUtils:
    def test_format_text(self):
        assert WeChatTransport.format_text("**bold**") == "bold"
        assert WeChatTransport.format_text("plain") == "plain"
