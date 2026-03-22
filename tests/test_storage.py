"""Test AccountStorage persistence."""

import json
import pytest
from pathlib import Path

from wechat_agent_sdk.account.storage import JsonFileStorage


@pytest.fixture
def tmp_storage(tmp_path):
    return JsonFileStorage(state_dir=tmp_path)


@pytest.mark.asyncio
async def test_token_roundtrip(tmp_storage):
    assert await tmp_storage.load_token("bot1") is None

    await tmp_storage.save_token("bot1", "tok_abc123")
    assert await tmp_storage.load_token("bot1") == "tok_abc123"


@pytest.mark.asyncio
async def test_cursor_roundtrip(tmp_storage):
    assert await tmp_storage.load_cursor("bot1") is None

    await tmp_storage.save_cursor("bot1", "cursor_xyz")
    assert await tmp_storage.load_cursor("bot1") == "cursor_xyz"


@pytest.mark.asyncio
async def test_multiple_accounts(tmp_storage):
    await tmp_storage.save_token("bot1", "tok_1")
    await tmp_storage.save_token("bot2", "tok_2")

    assert await tmp_storage.load_token("bot1") == "tok_1"
    assert await tmp_storage.load_token("bot2") == "tok_2"
    assert await tmp_storage.load_token("bot3") is None


@pytest.mark.asyncio
async def test_persistence_to_disk(tmp_path):
    storage = JsonFileStorage(state_dir=tmp_path)
    await storage.save_token("default", "my_token")
    await storage.save_cursor("default", "my_cursor")

    # Read the file directly
    data = json.loads((tmp_path / "accounts.json").read_text())
    assert data["default"]["token"] == "my_token"
    assert data["default"]["cursor"] == "my_cursor"

    # New storage instance should load from disk
    storage2 = JsonFileStorage(state_dir=tmp_path)
    assert await storage2.load_token("default") == "my_token"
    assert await storage2.load_cursor("default") == "my_cursor"


@pytest.mark.asyncio
async def test_overwrite_token(tmp_storage):
    await tmp_storage.save_token("bot1", "old")
    await tmp_storage.save_token("bot1", "new")
    assert await tmp_storage.load_token("bot1") == "new"


@pytest.mark.asyncio
async def test_empty_token_returns_none(tmp_storage):
    await tmp_storage.save_token("bot1", "")
    assert await tmp_storage.load_token("bot1") is None
