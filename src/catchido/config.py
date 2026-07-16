import os
import sys
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CONFIG_FILE = "config.toml"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Pictures" / "Catchido")
DEFAULT_LOG_FILE = "./logs/catchido.log"

_config_lock = threading.Lock()

@dataclass
class GeneralConfig:
    download_dir: str = DEFAULT_DOWNLOAD_DIR
    max_concurrent_downloads: int = 5
    auto_dedup: bool = True
    dedup_threshold: int = 5
    prefer_higher_res: bool = True
    download_photos: bool = True
    download_videos: bool = False
    log_level: str = "INFO"
    log_file: str = DEFAULT_LOG_FILE
    auto_scrape_interval_hours: int = 0

@dataclass
class TwitterConfig:
    bearer_token: str = ""
    rate_limit_wait: int = 15
    request_delay: int = 2
    include_retweets: bool = False
    min_resolution: List[int] = field(default_factory=lambda: [1080, 1080])

@dataclass
class WeiboConfig:
    cookie: str = ""
    use_playwright: bool = False
    request_delay: int = 2

@dataclass
class InstagramConfig:
    session_cookie: str = ""
    request_delay: int = 2

@dataclass
class ThreadsConfig:
    session_cookie: str = ""
    request_delay: int = 2

@dataclass
class TikTokConfig:
    session_cookie: str = ""
    request_delay: int = 3

@dataclass
class ProxyConfig:
    enabled: bool = False
    http: str = ""
    https: str = ""

@dataclass
class SearchConfig:
    min_relevance_score: float = 0.3
    auto_discover_accounts: bool = True
    auto_generate_keywords: bool = True
    include_fan_content: bool = True
    exclude_fanart: bool = True

@dataclass
class SourceConfig:
    platform: str
    username: Optional[str] = None
    user_id: Optional[str] = None
    type: str = "fansite"

@dataclass
class IdolConfig:
    name: str
    idol_type: str
    tags: List[str] = field(default_factory=list)
    profile: Dict[str, Any] = field(default_factory=dict)
    keywords: Dict[str, Any] = field(default_factory=dict)
    sources: List[SourceConfig] = field(default_factory=list)

@dataclass
class AppConfig:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    weibo: WeiboConfig = field(default_factory=WeiboConfig)
    instagram: InstagramConfig = field(default_factory=InstagramConfig)
    threads: ThreadsConfig = field(default_factory=ThreadsConfig)
    tiktok: TikTokConfig = field(default_factory=TikTokConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    idol: List[IdolConfig] = field(default_factory=list)

_config_instance: Optional[AppConfig] = None

def load_config(config_path: Optional[str] = None) -> AppConfig:
    global _config_instance
    with _config_lock:
        if _config_instance is not None and config_path is None:
            return _config_instance

        path = Path(config_path or CONFIG_FILE)
        if not path.exists():
            _config_instance = AppConfig()
            return _config_instance

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            print(f"Error loading config file {path}: {e}", file=sys.stderr)
            _config_instance = AppConfig()
            return _config_instance

        general_data = data.get("general", {})
        general = GeneralConfig(
            download_dir=general_data.get("download_dir", DEFAULT_DOWNLOAD_DIR),
            max_concurrent_downloads=general_data.get("max_concurrent_downloads", 5),
            auto_dedup=general_data.get("auto_dedup", True),
            dedup_threshold=general_data.get("dedup_threshold", 5),
            prefer_higher_res=general_data.get("prefer_higher_res", True),
            download_photos=general_data.get("download_photos", True),
            download_videos=general_data.get("download_videos", False),
            log_level=general_data.get("log_level", "INFO"),
            log_file=general_data.get("log_file", DEFAULT_LOG_FILE),
            auto_scrape_interval_hours=general_data.get("auto_scrape_interval_hours", 0),
        )

        twitter_data = data.get("twitter", {})
        twitter = TwitterConfig(
            bearer_token=twitter_data.get("bearer_token", ""),
            rate_limit_wait=twitter_data.get("rate_limit_wait", 15),
            include_retweets=twitter_data.get("include_retweets", False),
            min_resolution=twitter_data.get("min_resolution", [1080, 1080]),
        )

        weibo_data = data.get("weibo", {})
        weibo = WeiboConfig(
            cookie=weibo_data.get("cookie", ""),
            use_playwright=weibo_data.get("use_playwright", False),
            request_delay=weibo_data.get("request_delay", 2),
        )

        instagram_data = data.get("instagram", {})
        instagram = InstagramConfig(
            session_cookie=instagram_data.get("session_cookie", ""),
            request_delay=instagram_data.get("request_delay", 2)
        )

        threads_data = data.get("threads", {})
        threads = ThreadsConfig(
            session_cookie=threads_data.get("session_cookie", ""),
            request_delay=threads_data.get("request_delay", 2),
        )

        tiktok_data = data.get("tiktok", {})
        tiktok = TikTokConfig(
            session_cookie=tiktok_data.get("session_cookie", ""),
            request_delay=tiktok_data.get("request_delay", 3)
        )

        proxy_data = data.get("proxy", {})
        proxy = ProxyConfig(
            enabled=proxy_data.get("enabled", False),
            http=proxy_data.get("http", ""),
            https=proxy_data.get("https", ""),
        )

        search_data = data.get("search", {})
        search = SearchConfig(
            min_relevance_score=search_data.get("min_relevance_score", 0.3),
            auto_discover_accounts=search_data.get("auto_discover_accounts", True),
            auto_generate_keywords=search_data.get("auto_generate_keywords", True),
            include_fan_content=search_data.get("include_fan_content", True),
            exclude_fanart=search_data.get("exclude_fanart", True),
        )

        idol_list_raw = data.get("idol", data.get("oshi", []))
        idol_list = []
        for idol_data in idol_list_raw:
            name = idol_data.get("name")
            if not name:
                continue

            sources_list = []
            for src in idol_data.get("sources", []):
                sources_list.append(SourceConfig(
                    platform=src.get("platform"),
                    username=src.get("username"),
                    user_id=src.get("user_id"),
                    type=src.get("type", "fansite")
                ))

            idol_list.append(IdolConfig(
                name=name,
                idol_type=idol_data.get("idol_type", "jp"),
                tags=idol_data.get("tags", []),
                profile=idol_data.get("profile", {}),
                keywords=idol_data.get("keywords", {}),
                sources=sources_list
            ))

        _config_instance = AppConfig(
            general=general,
            twitter=twitter,
            weibo=weibo,
            instagram=instagram,
            threads=threads,
            tiktok=tiktok,
            proxy=proxy,
            search=search,
            idol=idol_list
        )
        return _config_instance

def get_config() -> AppConfig:
    global _config_instance
    with _config_lock:
        if _config_instance is None:
            return load_config()
        return _config_instance

def get_data_dir() -> Path:
    cfg = get_config()
    path = Path(cfg.general.download_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_log_dir() -> Path:
    cfg = get_config()
    path = Path(cfg.general.log_file).parent
    path.mkdir(parents=True, exist_ok=True)
    return path
