"""Tests for the dedup engine."""
import hashlib
import pytest
from pathlib import Path
from PIL import Image
from catchido.core.dedup import DedupEngine


@pytest.fixture
def dedup():
    return DedupEngine(threshold=5, prefer_higher_res=True)


@pytest.fixture
def sample_image(tmp_path):
    """Create a small test image."""
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    path = tmp_path / "test.jpg"
    img.save(path)
    return path


@pytest.fixture
def sample_image_similar(tmp_path):
    """Create a slightly different test image."""
    img = Image.new("RGB", (100, 100), color=(254, 0, 0))
    path = tmp_path / "test_similar.jpg"
    img.save(path)
    return path


class TestSHA256:
    def test_compute_sha256(self, dedup, sample_image):
        result = dedup.compute_sha256(sample_image)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

    def test_same_file_same_hash(self, dedup, sample_image):
        h1 = dedup.compute_sha256(sample_image)
        h2 = dedup.compute_sha256(sample_image)
        assert h1 == h2

    def test_different_files_different_hash(self, dedup, sample_image, sample_image_similar):
        h1 = dedup.compute_sha256(sample_image)
        h2 = dedup.compute_sha256(sample_image_similar)
        assert h1 != h2


class TestPerceptualHash:
    def test_compute_phash(self, dedup, sample_image):
        result = dedup.compute_phash(sample_image)
        assert result is not None
        assert isinstance(result, str)

    def test_compute_dhash(self, dedup, sample_image):
        result = dedup.compute_dhash(sample_image)
        assert result is not None
        assert isinstance(result, str)


class TestHammingDistance:
    def test_identical_hashes_distance_zero(self, dedup):
        h = "a" * 16
        assert dedup.hamming_distance(h, h) == 0

    def test_different_hashes_distance_positive(self, dedup):
        h1 = "0" * 16
        h2 = "f" * 16
        dist = dedup.hamming_distance(h1, h2)
        assert dist > 0

    def test_invalid_hash_returns_large_distance(self, dedup):
        assert dedup.hamming_distance("invalid", "also_invalid") == 999


class TestCheckDuplicate:
    @pytest.mark.asyncio
    async def test_nonexistent_file(self, dedup, tmp_path):
        fake_path = tmp_path / "nonexistent.jpg"
        from catchido.db import Database
        db_path = tmp_path / "test.db"
        async with Database(db_path) as db:
            await db.initialize()
            result = await dedup.check_duplicate(fake_path, db)
            assert result.is_duplicate is False
