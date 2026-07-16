# Oshi & Bias Hunter Project Rules & Guidelines

This document outlines the coding standards, architecture patterns, and conventions for the Oshi & Bias Hunter application. Any agent working on this codebase must follow these guidelines.

## Tech Stack & Architecture
- **Language**: Python 3.12+ (supports Python 3.14 features).
- **CLI Framework**: Click for CLI option/argument management.
- **Database**: SQLite with `aiosqlite` for async data access.
- **HTTP Client**: `httpx` (async) for API fetches and downloads.
- **Image Dedup**: Pillow and `imagehash` for perceptual similarity checks.
- **Async Pattern**: Coroutine wrappers with custom event loop run checks in CLI.

## Database Schema (`src/oshi_bias_hunter/db/repository.py`)
- `idol_profiles`: Core profile information (names, birthday, debut, status, etc.).
- `idol_keywords`: List of keywords and hashtags generated/registered for searching.
- `trusted_accounts`: Source accounts monitored for media uploads (Twitter, Weibo, Instagram).
- `media_hashes`: Perceptual and exact hashes of downloaded media to prevent duplicates.
- `download_checkpoints`: State storage tracking the last scraped post ID per platform per account.

## File Organization Rules (`src/oshi_bias_hunter/core/organizer.py`)
All files must be saved under the designated path pattern:
`{base_dir}/{group}/{idol_name}/{platform}/{photos|videos}/{YYYY-MM}/{filename}`

- **Group folder**: Prefixed with `🇯🇵 ` or `🇰🇷 ` flags based on type, defaults to `Solo`.
- **Media Type splitting**:
  - Video extensions (`.mp4`, `.mov`, `.mkv`, etc.) -> `videos` subfolder.
  - Image extensions (`.jpg`, `.jpeg`, `.png`, etc.) -> `photos` subfolder.
- **Monthly categorization**: ISO 8601 month string (`YYYY-MM`).
- **Filename convention**: `{username}_{post_id}_{index}.{ext}`.

## Coding Conventions
1. **Never Shadow Built-in Names**: Do not define functions with names like `list`, `dir`, `type`, etc., which shadows global built-in constructors. Override click names using `@cli.command("name")` while keeping python function names unique (e.g. `async def list_idols()`).
2. **REST Endpoints for Scrapers**: Instagram profile scraping should prefer the REST feed endpoint `https://www.instagram.com/api/v1/feed/user/{username}/username/` with valid `sessionid` cookies over GraphQL `query_hash` calls, due to Meta's aggressive signature checks and query_hash rotations.
3. **HTTPX Async Handling**: Always use `aiter_bytes()` (with an "a") for async chunk streaming instead of sync `iter_bytes()` to avoid `TypeError` on async loops.
4. **Folder Existence Guard**: Always call `.parent.mkdir(parents=True, exist_ok=True)` before creating metadata JSON logs (`_profile.json` and `_group_info.json`) to prevent `FileNotFoundError` on new folders.
5. **Windows Encoding fix**: Force `sys.stdout` and `sys.stderr` configuration to UTF-8 on Windows command lines to avoid crashes with Hangul or Kanji printouts.
