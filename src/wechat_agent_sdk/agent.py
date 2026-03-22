"""Abstract Agent interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import ChatRequest, ChatResponse


class Agent(ABC):
    """
    Abstract agent interface.

    Implement ``chat()`` to connect any AI backend to WeChat.
    The WeChat bridge calls ``chat()`` for each inbound message and sends
    the returned response back to the user.
    """

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a single message and return a reply."""
        ...

    async def on_start(self) -> None:
        """Called when the bot starts. Override for initialization."""

    async def on_stop(self) -> None:
        """Called when the bot stops. Override for cleanup."""
