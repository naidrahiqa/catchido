---
name: catchido-guide
description: Detailed commands guide, database maintenance routines, TUI manual, API configuration instructions, and troubleshooting tips for extending the Catchido application.
---

# Catchido Technical Guide

This skill guide provides operational instructions for running, debugging, and extending the `catchido` application.

## CLI Usage Reference

### 1. Registering Idols
```bash
# Add Saito Asuka (Japanese)
catchido add "Saito Asuka" --type jp --kanji "齋藤飛鳥" --group "乃木坂46" --company "Sony Music" --status graduated --twitter "@myfanaccount"

# Add Stella (Korean) with multiple platforms
catchido add "Stella" --type kr --hangul "김다현" --stage-name "Stella" --real-name "Stella Dahyun Kim" --group "Hearts2Hearts" --company "SM Entertainment" --fandom "S2U" --birthday "2007-06-18" --twitter "@Hearts2Hearts_SM" --instagram "@stella_h2h" --threads "@stella_h2h" --tiktok "@stella_tiktok"
```

### 2. Scraping and Downloading
```bash
# Download Stella's media (processes all platform sources)
catchido download "Stella"

# Download all tracked idols
catchido download --all

# Download with post limit per source
catchido download "Stella" --limit 50
```

### 3. Direct Post Grabbing
```bash
# Grab photos from a single tweet
catchido grab "https://twitter.com/username/status/123456789" --idol "Stella"

# Grab photos from an Instagram post/reel
catchido grab "https://www.instagram.com/p/C123abc/" --idol "Stella"

# Grab photos from a Threads post
catchido grab "https://www.threads.net/@username/post/C123abc" --idol "Stella"
```

### 4. Interactive Terminal UI (TUI)
```bash
# Launch full screen TUI dashboard
catchido tui
```

### 5. Interactive Web GUI Dashboard
```bash
# Launch full web dashboard (default at http://localhost:8000)
catchido web
```

### 6. Utilities
```bash
# List all tracked idols grouped by group
catchido list --by-group

# Show detailed profile and tracked accounts
catchido info "Stella"

# Get global download statistics
catchido stats

# Run manual photo/video reorganization
catchido organize

# Deduplicate images on disk (pHash threshold <= 5)
catchido dedup
```

## API Credentials Setup

### Twitter/X Developer API
1. Generate a **Bearer Token** (Twitter v2 API).
2. Save it in `config.toml`:
   ```toml
   [twitter]
   bearer_token = "YOUR_BEARER_TOKEN"
   ```

### Meta Platforms (Instagram & Threads)
1. Copy your session cookie from browser DevTools -> Cookies.
2. Save it in `config.toml`:
   ```toml
   [instagram]
   session_cookie = "550162..."
   
   [threads]
   session_cookie = "sessionid=550162..."
   ```

## Development and Extension

### Adding a New Scraper Platform
1. Create a scraper class in `src/catchido/scrapers/{platform}.py` inheriting from `BaseScraper`.
2. Implement `fetch_media()`, `fetch_media_from_url()`, and `get_hd_url()`.
3. Export it in `src/catchido/scrapers/__init__.py`.
4. Register it in `src/catchido/cli.py` and `src/catchido/tui/screens/download.py`.
