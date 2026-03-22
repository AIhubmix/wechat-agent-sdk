"""Test MessageMonitor (mocked client + agent)."""

import asyncio
import pytest

from wechat_agent_sdk import Agent, ChatRequest, ChatResponse
from wechat_agent_sdk.messaging.monitor import MessageMonitor


class RecordingAgent(Agent):
    """Agent that records received requests."""

    def __init__(self, reply: str = "ok"):
        self.requests: list[ChatRequest] = []
        self.reply = reply

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(text=self.reply)


class FakeClient:
    """Fake ILinkBotClient for testing."""

    def __init__(self):
        self.messages_to_return: list[list[dict]] = []
        self.sent_messages: list[tuple[str, str, str]] = []
        self.call_count = 0
        self._token = "fake_token"

    @property
    def token(self):
        return self._token

    async def get_updates(self, cursor: str = ""):
        self.call_count += 1
        if self.messages_to_return:
            msgs = self.messages_to_return.pop(0)
            return msgs, f"cursor_{self.call_count}"
        # Simulate long-poll delay to avoid tight loop
        await asyncio.sleep(0.05)
        return [], cursor

    async def send_message(self, to_user_id: str, text: str, context_token: str = ""):
        self.sent_messages.append((to_user_id, text, context_token))

    async def send_typing(self, to_user_id: str, ticket: str, start: bool = True):
        pass

    async def get_config(self, to_user_id: str, context_token: str = ""):
        return {}


@pytest.mark.asyncio
async def test_monitor_dispatches_message():
    agent = RecordingAgent(reply="pong")
    client = FakeClient()
    client.messages_to_return = [
        [
            {
                "from_user_id": "wxid_test",
                "message_type": 1,
                "message_id": "msg_001",
                "context_token": "ctx_1",
                "item_list": [{"type": 1, "text_item": {"text": "ping"}}],
            }
        ],
    ]

    monitor = MessageMonitor(client, agent)
    await monitor.start()

    # Wait for message to be processed
    for _ in range(20):
        await asyncio.sleep(0.05)
        if agent.requests:
            break

    await monitor.stop()

    assert len(agent.requests) == 1
    assert agent.requests[0].text == "ping"
    assert agent.requests[0].conversation_id == "wxid_test"

    # Verify reply was sent
    assert len(client.sent_messages) == 1
    assert client.sent_messages[0][0] == "wxid_test"  # to_user_id
    assert client.sent_messages[0][1] == "pong"  # text


@pytest.mark.asyncio
async def test_monitor_dedup():
    agent = RecordingAgent()
    client = FakeClient()
    # Same message_id twice
    msg = {
        "from_user_id": "wxid_test",
        "message_type": 1,
        "message_id": "msg_dup",
        "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
    }
    client.messages_to_return = [[msg], [msg]]

    monitor = MessageMonitor(client, agent)
    await monitor.start()

    for _ in range(30):
        await asyncio.sleep(0.05)
        if client.call_count >= 3:
            break

    await monitor.stop()

    # Should only be processed once despite being returned twice
    assert len(agent.requests) == 1


@pytest.mark.asyncio
async def test_monitor_filters_bot_messages():
    agent = RecordingAgent()
    client = FakeClient()
    client.messages_to_return = [
        [
            {
                "from_user_id": "wxid_test",
                "message_type": 2,  # BOT message
                "message_id": "msg_bot",
                "item_list": [{"type": 1, "text_item": {"text": "bot says"}}],
            }
        ],
    ]

    monitor = MessageMonitor(client, agent)
    await monitor.start()

    await asyncio.sleep(0.2)
    await monitor.stop()

    assert len(agent.requests) == 0


@pytest.mark.asyncio
async def test_monitor_cursor_updated():
    agent = RecordingAgent()
    client = FakeClient()
    client.messages_to_return = [
        [
            {
                "from_user_id": "wxid_test",
                "message_type": 1,
                "message_id": "msg_1",
                "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
            }
        ],
    ]

    monitor = MessageMonitor(client, agent)
    monitor.cursor = "old_cursor"
    await monitor.start()

    for _ in range(20):
        await asyncio.sleep(0.05)
        if monitor.cursor != "old_cursor":
            break

    await monitor.stop()

    assert monitor.cursor.startswith("cursor_")


@pytest.mark.asyncio
async def test_monitor_context_token_cached():
    agent = RecordingAgent()
    client = FakeClient()
    client.messages_to_return = [
        [
            {
                "from_user_id": "wxid_user1",
                "message_type": 1,
                "message_id": "msg_ctx",
                "context_token": "ctx_token_123",
                "item_list": [{"type": 1, "text_item": {"text": "with context"}}],
            }
        ],
    ]

    monitor = MessageMonitor(client, agent)
    await monitor.start()

    for _ in range(20):
        await asyncio.sleep(0.05)
        if agent.requests:
            break

    await monitor.stop()

    # context_token should be cached and used in reply
    assert client.sent_messages[0][2] == "ctx_token_123"


@pytest.mark.asyncio
async def test_monitor_agent_error_sends_error_notice():
    class FailingAgent(Agent):
        async def chat(self, request):
            raise ValueError("something broke")

    agent = FailingAgent()
    client = FakeClient()
    client.messages_to_return = [
        [
            {
                "from_user_id": "wxid_test",
                "message_type": 1,
                "message_id": "msg_fail",
                "item_list": [{"type": 1, "text_item": {"text": "trigger error"}}],
            }
        ],
    ]

    monitor = MessageMonitor(client, agent)
    await monitor.start()

    for _ in range(20):
        await asyncio.sleep(0.05)
        if client.sent_messages:
            break

    await monitor.stop()

    # Should send error notice to user
    assert len(client.sent_messages) == 1
    assert "失败" in client.sent_messages[0][1]
