"""Test SQLite storage backend."""

import pytest

aiosqlite = pytest.importorskip("aiosqlite", reason="aiosqlite not installed")

from wechat_agent_sdk.account.sqlite_storage import SqliteStorage


@pytest.mark.asyncio
async def test_token_roundtrip(tmp_path):
    db_path = str(tmp_path / "test.db")
    storage = SqliteStorage(db_path=db_path)

    assert await storage.load_token("bot1") is None
    await storage.save_token("bot1", "tok_123")
    assert await storage.load_token("bot1") == "tok_123"
    await storage.close()


@pytest.mark.asyncio
async def test_cursor_roundtrip(tmp_path):
    db_path = str(tmp_path / "test.db")
    storage = SqliteStorage(db_path=db_path)

    assert await storage.load_cursor("bot1") is None
    await storage.save_cursor("bot1", "cur_abc")
    assert await storage.load_cursor("bot1") == "cur_abc"
    await storage.close()


@pytest.mark.asyncio
async def test_meta_roundtrip(tmp_path):
    db_path = str(tmp_path / "test.db")
    storage = SqliteStorage(db_path=db_path)

    assert await storage.load_meta("bot1") is None
    meta = {"bot_id": "b123", "base_url": "https://example.com"}
    await storage.save_meta("bot1", meta)
    loaded = await storage.load_meta("bot1")
    assert loaded == meta
    await storage.close()


@pytest.mark.asyncio
async def test_multiple_accounts(tmp_path):
    db_path = str(tmp_path / "test.db")
    storage = SqliteStorage(db_path=db_path)

    await storage.save_token("bot1", "tok_1")
    await storage.save_token("bot2", "tok_2")

    assert await storage.load_token("bot1") == "tok_1"
    assert await storage.load_token("bot2") == "tok_2"
    await storage.close()


@pytest.mark.asyncio
async def test_persistence_across_instances(tmp_path):
    db_path = str(tmp_path / "test.db")

    s1 = SqliteStorage(db_path=db_path)
    await s1.save_token("bot1", "persistent_tok")
    await s1.close()

    s2 = SqliteStorage(db_path=db_path)
    assert await s2.load_token("bot1") == "persistent_tok"
    await s2.close()


@pytest.mark.asyncio
async def test_overwrite(tmp_path):
    db_path = str(tmp_path / "test.db")
    storage = SqliteStorage(db_path=db_path)

    await storage.save_token("bot1", "old")
    await storage.save_token("bot1", "new")
    assert await storage.load_token("bot1") == "new"
    await storage.close()
