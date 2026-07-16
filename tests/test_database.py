"""Tests for the database repository."""
import pytest
import json
from catchido.db import Database
from catchido.db.models import (
    IdolProfile, IdolType, IdolStatus, TrustedAccount,
    IdolKeywordEntry, MediaHash, DownloadCheckpoint,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    async with Database(db_path) as database:
        await database.initialize()
        yield database


class TestIdolCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get_idol(self, db):
        profile = IdolProfile(
            display_name="Test Idol",
            idol_type=IdolType.JAPANESE,
            kanji_name="テストアイドル",
            group_name="Test Group",
        )
        result = await db.add_idol(profile)
        assert result is True

        fetched = await db.get_idol("Test Idol")
        assert fetched is not None
        assert fetched.display_name == "Test Idol"
        assert fetched.idol_type == IdolType.JAPANESE
        assert fetched.kanji_name == "テストアイドル"

    @pytest.mark.asyncio
    async def test_list_idols(self, db):
        await db.add_idol(IdolProfile(display_name="A", idol_type=IdolType.JAPANESE))
        await db.add_idol(IdolProfile(display_name="B", idol_type=IdolType.KOREAN))
        idols = await db.list_idols()
        assert len(idols) == 2

    @pytest.mark.asyncio
    async def test_delete_idol(self, db):
        await db.add_idol(IdolProfile(display_name="To Delete", idol_type=IdolType.JAPANESE))
        result = await db.delete_idol("To Delete")
        assert result is True
        assert await db.get_idol("To Delete") is None

    @pytest.mark.asyncio
    async def test_list_by_group(self, db):
        await db.add_idol(IdolProfile(display_name="M1", idol_type=IdolType.JAPANESE, group_name="GroupA"))
        await db.add_idol(IdolProfile(display_name="M2", idol_type=IdolType.JAPANESE, group_name="GroupA"))
        await db.add_idol(IdolProfile(display_name="M3", idol_type=IdolType.KOREAN, group_name="GroupB"))
        result = await db.list_by_group("GroupA")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_update_idol(self, db):
        await db.add_idol(IdolProfile(display_name="Updatable", idol_type=IdolType.JAPANESE))
        updated = IdolProfile(
            display_name="Updatable",
            idol_type=IdolType.KOREAN,
            group_name="New Group",
        )
        result = await db.update_idol("Updatable", updated)
        assert result is True
        fetched = await db.get_idol("Updatable")
        assert fetched.group_name == "New Group"


class TestKeywordOperations:
    @pytest.mark.asyncio
    async def test_add_and_get_keywords(self, db):
        await db.add_idol(IdolProfile(display_name="Kw Idol", idol_type=IdolType.JAPANESE))
        entry = IdolKeywordEntry(
            idol_name="Kw Idol",
            idol_type=IdolType.JAPANESE,
            keyword="テスト",
            script_type="kanji",
            platform="all",
        )
        await db.add_keyword(entry)
        keywords = await db.get_keywords_for_idol("Kw Idol")
        assert len(keywords) == 1
        assert keywords[0].keyword == "テスト"

    @pytest.mark.asyncio
    async def test_keyword_unique_constraint(self, db):
        await db.add_idol(IdolProfile(display_name="Dup Idol", idol_type=IdolType.JAPANESE))
        entry = IdolKeywordEntry(
            idol_name="Dup Idol", idol_type=IdolType.JAPANESE,
            keyword="same", platform="all",
        )
        await db.add_keyword(entry)
        await db.add_keyword(entry)  # duplicate
        keywords = await db.get_keywords_for_idol("Dup Idol")
        assert len(keywords) == 1


class TestTrustedAccountOperations:
    @pytest.mark.asyncio
    async def test_add_and_get_trusted(self, db):
        await db.add_idol(IdolProfile(display_name="TA Idol", idol_type=IdolType.JAPANESE))
        acc = TrustedAccount(
            idol_name="TA Idol",
            platform="twitter",
            username="fan_account",
            account_type="fansite",
        )
        await db.add_trusted_account(acc)
        accounts = await db.get_trusted_accounts("TA Idol")
        assert len(accounts) == 1
        assert accounts[0].username == "fan_account"

    @pytest.mark.asyncio
    async def test_is_trusted(self, db):
        await db.add_idol(IdolProfile(display_name="Trust Test", idol_type=IdolType.JAPANESE))
        await db.add_trusted_account(TrustedAccount(
            idol_name="Trust Test", platform="twitter", username="trusted_user",
        ))
        assert await db.is_trusted("twitter", "trusted_user", "Trust Test") is True
        assert await db.is_trusted("twitter", "unknown_user", "Trust Test") is False


class TestMediaHashOperations:
    @pytest.mark.asyncio
    async def test_add_and_check_sha256(self, db):
        mh = MediaHash(
            file_path="/test/photo.jpg",
            sha256="abc123def456",
            file_size=1024,
        )
        await db.add_media_hash(mh)
        result = await db.check_sha256_exists("abc123def456")
        assert result == "/test/photo.jpg"

    @pytest.mark.asyncio
    async def test_sha256_not_found(self, db):
        result = await db.check_sha256_exists("nonexistent")
        assert result is None


class TestCheckpointOperations:
    @pytest.mark.asyncio
    async def test_update_and_get_checkpoint(self, db):
        cp = DownloadCheckpoint(
            idol_name="CP Idol",
            platform="twitter",
            source_username="fansite",
            last_id="12345",
        )
        await db.update_checkpoint(cp)
        result = await db.get_checkpoint("CP Idol", "twitter", "fansite")
        assert result == "12345"


class TestStats:
    @pytest.mark.asyncio
    async def test_get_download_stats_empty(self, db):
        stats = await db.get_download_stats()
        assert stats["total_count"] == 0
        assert stats["total_size"] == 0

    @pytest.mark.asyncio
    async def test_get_media_count(self, db):
        count = await db.get_media_count()
        assert count == 0
