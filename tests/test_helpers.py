"""Tests for utility helpers."""
import pytest
from catchido.utils.helpers import (
    sanitize_filename,
    format_filesize,
    get_file_extension,
    ensure_dir,
    timestamp_now,
)


class TestSanitizeFilename:
    def test_removes_invalid_chars(self):
        assert sanitize_filename('file<>:"/\\|?*name') == "filename"

    def test_collapses_spaces(self):
        assert sanitize_filename("hello   world") == "hello world"

    def test_strips_whitespace(self):
        assert sanitize_filename("  hello  ") == "hello"

    def test_preserves_normal_name(self):
        assert sanitize_filename("normal_file.jpg") == "normal_file.jpg"

    def test_handles_unicode(self):
        result = sanitize_filename("齋藤飛鳥")
        assert result == "齋藤飛鳥"


class TestFormatFilesize:
    def test_zero_bytes(self):
        assert format_filesize(0) == "0B"

    def test_kilobytes(self):
        result = format_filesize(1024)
        assert "KB" in result

    def test_megabytes(self):
        result = format_filesize(1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        result = format_filesize(1024 ** 3)
        assert "GB" in result


class TestGetFileExtension:
    def test_jpg_url(self):
        assert get_file_extension("https://example.com/photo.jpg") == "jpg"

    def test_png_url(self):
        assert get_file_extension("https://example.com/photo.png") == "png"

    def test_mp4_url(self):
        assert get_file_extension("https://example.com/video.mp4") == "mp4"

    def test_format_query_param(self):
        assert get_file_extension("https://pbs.twimg.com/media/abc?format=jpg&name=4096x4096") == "jpg"

    def test_unknown_defaults_to_jpg(self):
        assert get_file_extension("https://example.com/photo") == "jpg"

    def test_webp(self):
        assert get_file_extension("https://example.com/photo.webp") == "webp"


class TestEnsureDir:
    def test_creates_directory(self, tmp_path):
        new_dir = tmp_path / "new" / "nested"
        result = ensure_dir(new_dir)
        assert result.exists()
        assert result.is_dir()

    def test_existing_directory(self, tmp_path):
        result = ensure_dir(tmp_path)
        assert result.exists()


class TestTimestampNow:
    def test_returns_iso_format(self):
        ts = timestamp_now()
        assert "T" in ts
        assert len(ts) > 10
