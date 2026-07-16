# 🎯 Catchido — Smart HD Media Scraper, Dedup & Organizer

> **Catchido** (derived from "Catch" + "Idol") is a highly modular, asynchronous console tool and interactive Terminal User Interface (TUI) designed to automatically scrape, catalog, deduplicate, and archive high-definition photos of your favorite Japanese idols (Oshi) and Korean idols (Bias).

It monitors official and fansite accounts across five major social networks: **Instagram**, **Threads**, **X (Twitter)**, **TikTok**, and **Weibo**.

---

## 🌟 Key Features

- **📺 Interactive Terminal UI (TUI)**: Fully-featured terminal dashboard with tracked lists, profile inspect, settings viewer, and real-time log panels built using the **Textual** framework.
- **🔗 Multi-Platform Scraping**: Supports scraping profiles and post links across X/Twitter, Instagram, Threads, TikTok (photo slideshows/carousels), and Weibo.
- **🧩 Smart Name Resolution**: Handles multi-script name variants automatically (Kanji, Hiragana, Katakana, Romanizations, and Korean Hangul/Stage names) to build optimized search queries.
- **🖼️ Perceptual Deduplication**: Leverages exact SHA-256 and Perceptual Hashing (pHash) to filter out duplicate images. If a higher-resolution version of an existing image is found, Catchido automatically replaces the lower-quality file.
- **📂 Structured Storage**: Automatically archives downloads into a clean, human-readable directory tree: `data/{Group Name}/{Idol Name}/{Platform}/{photos}/{YYYY-MM}/{filename}`.

---

## 🛠️ Installation & Setup

This tool requires Python 3.12+.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/catchido.git
   cd catchido
   ```

2. **Initialize virtual environment and install with TUI dependencies**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # On Windows
   source .venv/bin/activate # On Unix/macOS
   
   pip install -e .[tui]
   ```

3. **Initialize local database & config file**:
   ```bash
   catchido init
   ```

---

## ⚙️ Configuration (`config.toml`)

Open `config.toml` and configure your API tokens and session cookies:
- **Twitter/X**: Add a Bearer Token in `[twitter]` section.
- **Instagram / Threads**: Paste your browser `sessionid` cookie in the `[instagram]` and `[threads]` sections to bypass profile rate limits.
- **TikTok / Weibo**: Add your session cookies in `[tiktok]` and `[weibo]` to fetch original resolutions.

See the [SETUP_GUIDE.md](file:///D:/Dev/Project-Coding/2026/7Juli/oshi_bias_hunter/SETUP_GUIDE.md) for step-by-step instructions on obtaining cookies and tokens.

---

## 🖥️ Usage Reference

### 1. Interactive Web GUI Dashboard (Recommended)
Launch the beautiful browser-based dashboard to manage your collection, view download stats, run scrapes, and browse your HD media gallery in a beautiful grid:
```bash
catchido web
```
Open your browser at `http://localhost:8000`.

### 2. Interactive Terminal UI (TUI)
Launch the terminal dashboard:
```bash
catchido tui
```
*Hotkeys inside TUI*:
- `h`: Home / Dashboard overview
- `i`: Tracked Idols database list
- `d`: Scraper control & Download monitor
- `s`: Settings viewer
- `q`: Exit

### 3. CLI commands
If you prefer traditional command execution (e.g. for cron/automation):

#### Registering an Idol
```bash
# Add Saito Asuka (Japanese Idol)
catchido add "Saito Asuka" --type jp --kanji "齋藤飛鳥" --group "乃木坂46" --company "Sony Music" --status graduated --twitter "@myfanaccount" --instagram "@asaborhythm_official"

# Add Jisoo (Korean Idol) with Threads and TikTok
catchido add "Jisoo" --type kr --hangul "김지수" --stage-name "Jisoo" --group "BLACKPINK" --company "YG Entertainment" --instagram "@sooyaaa__" --threads "@sooyaaa__" --tiktok "@bp_tiktok"
```

#### Scraping & Downloading
```bash
# Scrape and download new media for a specific idol
catchido download "Jisoo"

# Scrape all tracked idols
catchido download --all
```

#### Grabbing Specific Posts
```bash
# Grab media from a single post/tweet/thread
catchido grab "https://www.threads.net/@sooyaaa__/post/C123abc" --idol "Jisoo"
```

#### Maintenance
```bash
# List all tracked idols
catchido list --by-group

# Show detailed profile overview
catchido info "Jisoo"

# Run perceptual duplicate cleanup scan
catchido dedup
```
