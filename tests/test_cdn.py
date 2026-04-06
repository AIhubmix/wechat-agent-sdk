"""Test CDN upload/download + media send/receive pipeline (mocked HTTP)."""

import base64
import hashlib
import pytest
import httpx

from wechat_agent_sdk.media.crypto import encrypt, generate_aes_key, decrypt, decode_aes_key
from wechat_agent_sdk.media.cdn import download_media, upload_media, CDN_BASE
from wechat_agent_sdk.transport import _build_media_item


# ── CDN download tests ──


class TestCdnDownload:
    @pytest.mark.asyncio
    async def test_download_and_decrypt(self):
        """download_media should fetch from CDN and AES-decrypt the content."""
        original = b"hello this is an image file content"
        key = generate_aes_key()
        encrypted = encrypt(original, key)
        aes_key_b64 = base64.b64encode(key).decode()

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            assert "encrypted_query_param=cdn_param_abc" in str(request.url)
            return httpx.Response(200, content=encrypted)

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await download_media(
                client, "cdn_param_abc", aes_key_b64
            )

        assert result == original

    @pytest.mark.asyncio
    async def test_download_with_hex_key(self):
        """download_media should handle image_item.aeskey (hex format)."""
        original = b"png image data here"
        key = generate_aes_key()
        encrypted = encrypt(original, key)
        hex_key = key.hex()

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=encrypted)

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await download_media(
                client, "cdn_param_xyz", "", aeskey_hex=hex_key
            )

        assert result == original

    @pytest.mark.asyncio
    async def test_download_http_error_raises(self):
        """download_media should raise on HTTP error."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="CDN error")

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await download_media(client, "bad_param", base64.b64encode(b"\x00" * 16).decode())


# ── CDN upload tests ──


class MockBotClient:
    """Mock ILinkBotClient for upload tests."""

    def __init__(self):
        self.upload_calls = []

    async def get_upload_url(self, **kwargs):
        self.upload_calls.append(kwargs)
        return {"upload_param": "presigned_upload_param_123"}


class TestCdnUpload:
    @pytest.mark.asyncio
    async def test_upload_full_pipeline(self):
        """upload_media: encrypt → getuploadurl → CDN POST → return cdn_info."""
        file_data = b"test file content for upload"
        cdn_response_param = "cdn_encrypted_result_abc"

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            # CDN upload endpoint
            if "/upload" in str(request.url):
                assert "encrypted_query_param=presigned_upload_param_123" in str(request.url)
                assert request.headers.get("content-type") == "application/octet-stream"

                # Verify body is encrypted (not raw)
                body = request.content
                assert body != file_data
                assert len(body) > 0

                return httpx.Response(
                    200,
                    headers={"x-encrypted-param": cdn_response_param},
                )
            return httpx.Response(404)

        bot_client = MockBotClient()
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            cdn_info = await upload_media(
                bot_client=bot_client,
                http_client=http_client,
                to_user_id="user_123",
                file_data=file_data,
                media_type=1,  # IMAGE
                file_name="photo.jpg",
            )

        # Verify cdn_info structure
        assert cdn_info["encrypt_query_param"] == cdn_response_param
        assert cdn_info["encrypt_type"] == 1
        assert cdn_info["aes_key"]  # should be a base64 string

        # Verify the AES key in cdn_info can decrypt what was uploaded
        key = decode_aes_key(cdn_info["aes_key"])
        assert len(key) == 16

        # Verify bot_client.get_upload_url was called correctly
        assert len(bot_client.upload_calls) == 1
        call = bot_client.upload_calls[0]
        assert call["media_type"] == 1
        assert call["to_user_id"] == "user_123"
        assert call["raw_size"] == len(file_data)
        assert call["raw_file_md5"] == hashlib.md5(file_data).hexdigest()

    @pytest.mark.asyncio
    async def test_upload_no_upload_param_raises(self):
        """upload_media should raise if getuploadurl returns no upload_param."""

        class BadBotClient:
            async def get_upload_url(self, **kwargs):
                return {}  # missing upload_param

        transport = httpx.MockTransport(lambda r: httpx.Response(200))
        async with httpx.AsyncClient(transport=transport) as http_client:
            with pytest.raises(RuntimeError, match="upload_param"):
                await upload_media(
                    bot_client=BadBotClient(),
                    http_client=http_client,
                    to_user_id="user_1",
                    file_data=b"data",
                    media_type=1,
                )

    @pytest.mark.asyncio
    async def test_upload_no_cdn_header_raises(self):
        """upload_media should raise if CDN response lacks x-encrypted-param."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)  # no x-encrypted-param header

        bot_client = MockBotClient()
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            with pytest.raises(RuntimeError, match="x-encrypted-param"):
                await upload_media(
                    bot_client=bot_client,
                    http_client=http_client,
                    to_user_id="user_1",
                    file_data=b"data",
                    media_type=3,  # FILE
                )

    @pytest.mark.asyncio
    async def test_upload_roundtrip_decrypt(self):
        """Uploaded encrypted data should be decryptable with the returned key."""
        file_data = b"PDF file content here " * 100  # ~2.2KB
        captured_body = {}

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_body["data"] = request.content
            return httpx.Response(
                200, headers={"x-encrypted-param": "cdn_result"}
            )

        bot_client = MockBotClient()
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            cdn_info = await upload_media(
                bot_client=bot_client,
                http_client=http_client,
                to_user_id="user_1",
                file_data=file_data,
                media_type=3,
            )

        # Decrypt what was uploaded using the returned key
        key = decode_aes_key(cdn_info["aes_key"])
        decrypted = decrypt(captured_body["data"], key)
        assert decrypted == file_data


# ── _build_media_item tests ──


class TestBuildMediaItem:
    def test_image_item(self):
        cdn_info = {"encrypt_query_param": "p1", "aes_key": "k1", "encrypt_type": 1}
        item = _build_media_item("image", cdn_info)
        assert item["type"] == 2
        assert item["image_item"]["media"]["encrypt_query_param"] == "p1"

    def test_video_item(self):
        cdn_info = {"encrypt_query_param": "p2", "aes_key": "k2", "encrypt_type": 1}
        item = _build_media_item("video", cdn_info)
        assert item["type"] == 5
        assert "video_item" in item

    def test_voice_item(self):
        cdn_info = {"encrypt_query_param": "p3", "aes_key": "k3", "encrypt_type": 1}
        item = _build_media_item("voice", cdn_info)
        assert item["type"] == 3
        assert "voice_item" in item

    def test_file_item(self):
        cdn_info = {"encrypt_query_param": "p4", "aes_key": "k4", "encrypt_type": 1}
        item = _build_media_item("file", cdn_info, file_name="report.pdf")
        assert item["type"] == 4
        assert item["file_item"]["media"]["encrypt_query_param"] == "p4"
        assert item["file_item"]["file_name"] == "report.pdf"

    def test_file_item_no_name(self):
        cdn_info = {"encrypt_query_param": "p5", "aes_key": "k5", "encrypt_type": 1}
        item = _build_media_item("file", cdn_info)
        assert item["type"] == 4
        assert "file_name" not in item["file_item"]

    def test_unknown_type_defaults_to_file(self):
        cdn_info = {"encrypt_query_param": "p6", "aes_key": "k6", "encrypt_type": 1}
        item = _build_media_item("unknown", cdn_info)
        assert item["type"] == 4  # file type
        assert "file_item" in item


# ── Transport send_media / download_media integration tests ──


class TestTransportMedia:
    @pytest.mark.asyncio
    async def test_transport_download_media(self):
        """transport.download_media() should download and decrypt."""
        from wechat_agent_sdk import WeChatTransport
        from wechat_agent_sdk.types import MediaInfo

        original = b"image bytes here"
        key = generate_aes_key()
        encrypted = encrypt(original, key)
        aes_key_b64 = base64.b64encode(key).decode()

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            if "encrypted_query_param" in str(request.url):
                return httpx.Response(200, content=encrypted)
            return httpx.Response(200, json={})  # for any other calls

        transport = WeChatTransport(account_id="test", token="tok")
        transport._client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(mock_handler)
        )

        media = MediaInfo(
            type="image",
            cdn_param="test_cdn_param",
            aes_key=aes_key_b64,
        )
        result = await transport.download_media(media)
        assert result == original

    @pytest.mark.asyncio
    async def test_transport_send_media(self):
        """transport.send_media() should encrypt, upload, and send."""
        from wechat_agent_sdk import WeChatTransport

        file_data = b"video file content"
        sent_messages = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)

            # getuploadurl
            if "getuploadurl" in url:
                return httpx.Response(200, json={"upload_param": "up_param"})
            # CDN upload
            if "/upload" in url:
                return httpx.Response(
                    200, headers={"x-encrypted-param": "cdn_result_param"}
                )
            # sendmessage
            if "sendmessage" in url:
                body = request.content
                sent_messages.append(body)
                return httpx.Response(200, json={"ret": 0})
            return httpx.Response(200, json={})

        transport = WeChatTransport(account_id="test", token="tok")
        transport._client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(mock_handler)
        )

        await transport.send_media(
            chat_id="user_456",
            file_data=file_data,
            media_type="video",
            file_name="clip.mp4",
            context_token="ctx_123",
        )

        # Verify sendmessage was called
        assert len(sent_messages) == 1

        import json
        msg = json.loads(sent_messages[0])
        assert msg["msg"]["to_user_id"] == "user_456"
        assert msg["msg"]["context_token"] == "ctx_123"
        item = msg["msg"]["item_list"][0]
        assert item["type"] == 5  # video
        assert item["video_item"]["media"]["encrypt_query_param"] == "cdn_result_param"
