"""Test ILinkBotClient (mocked HTTP)."""

import json
import pytest
import httpx

from wechat_agent_sdk.api.client import ILinkBotClient, SessionExpiredError


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns pre-configured responses."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, httpx.Response] = {}

    def set_response(self, path: str, data: dict, status_code: int = 200):
        self.responses[path] = httpx.Response(
            status_code=status_code,
            json=data,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.responses:
            return self.responses[path]
        return httpx.Response(404, text="Not found")


@pytest.fixture
def mock_transport():
    return MockTransport()


@pytest.fixture
def client(mock_transport):
    c = ILinkBotClient(token="test_token")
    # Override the internal client with our mock
    c._client = httpx.AsyncClient(transport=mock_transport, base_url="https://test.example.com")
    c._client.headers["Authorization"] = "Bearer test_token"
    return c, mock_transport


@pytest.mark.asyncio
async def test_get_updates_success(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/getupdates", {
        "ret": 0,
        "msgs": [
            {
                "from_user_id": "wxid_user1",
                "message_type": 1,
                "message_id": "msg_001",
                "context_token": "ctx_abc",
                "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
            }
        ],
        "get_updates_buf": "cursor_new",
    })

    msgs, cursor = await api_client.get_updates("")
    assert len(msgs) == 1
    assert msgs[0]["from_user_id"] == "wxid_user1"
    assert cursor == "cursor_new"


@pytest.mark.asyncio
async def test_get_updates_empty(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/getupdates", {
        "ret": 0,
        "msgs": [],
        "get_updates_buf": "same_cursor",
    })

    msgs, cursor = await api_client.get_updates("same_cursor")
    assert msgs == []
    assert cursor == "same_cursor"


@pytest.mark.asyncio
async def test_get_updates_session_expired(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/getupdates", {
        "ret": 0,
        "errcode": -14,
        "errmsg": "session expired",
        "msgs": [],
    })

    with pytest.raises(SessionExpiredError):
        await api_client.get_updates("")


@pytest.mark.asyncio
async def test_send_message(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/sendmessage", {"ret": 0})

    await api_client.send_message("wxid_user1", "hello back", "ctx_abc")

    assert len(transport.requests) == 1
    req = transport.requests[0]
    body = json.loads(req.content)
    assert body["msg"]["to_user_id"] == "wxid_user1"
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "hello back"
    assert body["msg"]["context_token"] == "ctx_abc"
    assert body["msg"]["message_type"] == 2  # BOT
    assert body["msg"]["message_state"] == 2  # FINISH


@pytest.mark.asyncio
async def test_send_typing(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/sendtyping", {})

    await api_client.send_typing("wxid_user1", "ticket_123", start=True)
    assert len(transport.requests) == 1

    body = json.loads(transport.requests[0].content)
    assert body["ilink_user_id"] == "wxid_user1"
    assert body["typing_ticket"] == "ticket_123"
    assert body["status"] == 1  # TYPING


@pytest.mark.asyncio
async def test_get_config(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/getconfig", {
        "typing_ticket": "ticket_456",
    })

    data = await api_client.get_config("wxid_user1")
    assert data["typing_ticket"] == "ticket_456"


@pytest.mark.asyncio
async def test_request_qrcode(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/get_bot_qrcode", {
        "qrcode_img_content": "https://login.weixin.qq.com/qr/xxx",
        "qrcode": "uuid_abc",
        "ret": 0,
    })

    result = await api_client.request_qrcode()
    assert result["qrcode_url"] == "https://login.weixin.qq.com/qr/xxx"
    assert result["uuid"] == "uuid_abc"


@pytest.mark.asyncio
async def test_check_login_confirmed(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/get_qrcode_status", {
        "status": "confirmed",
        "bot_token": "new_bot_token",
        "ilink_bot_id": "bot123@im.bot",
        "ilink_user_id": "user456@im.wechat",
        "baseurl": "https://ilinkai.weixin.qq.com",
    })

    result = await api_client.check_login_status("uuid_abc")
    assert result["status"] == "confirmed"
    assert result["token"] == "new_bot_token"
    assert result["bot_id"] == "bot123@im.bot"


@pytest.mark.asyncio
async def test_check_login_pending(client):
    api_client, transport = client
    transport.set_response("/ilink/bot/get_qrcode_status", {
        "ret": 0,
    })

    result = await api_client.check_login_status("uuid_abc")
    # ret=0 but no token — still pending
    assert result["status"] in ("pending", "confirmed")


@pytest.mark.asyncio
async def test_close(client):
    api_client, _ = client
    await api_client.close()
    assert api_client._client is None
