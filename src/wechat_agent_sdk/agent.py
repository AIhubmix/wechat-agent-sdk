"""Abstract Agent interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional

from .types import ChatRequest, ChatResponse

# Callback type for sending intermediate messages during long-running agent tasks.
# signature: async def sender(text: str) -> None
MessageSender = Callable[[str], Awaitable[None]]


class Agent(ABC):
    """
    Abstract agent interface.

    Implement ``chat()`` to connect any AI backend to WeChat.
    The WeChat bridge calls ``chat()`` for each inbound message and sends
    the returned response back to the user.
    """

    _message_sender: Optional[MessageSender] = None

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a single message and return a reply."""
        ...

    def set_message_sender(self, sender: MessageSender) -> None:
        """
        Inject a callback for sending intermediate messages to the user.

        The monitor calls this before starting the message loop, allowing
        agents (e.g. AcpAgent) to stream partial results to WeChat during
        long-running operations like tool calls.
        """
        self._message_sender = sender

    async def on_start(self) -> None:
        """Called when the bot starts. Override for initialization."""

    async def on_stop(self) -> None:
        """Called when the bot stops. Override for cleanup."""
