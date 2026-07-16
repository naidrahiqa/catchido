import json
import asyncio
import queue
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, field_validator

from ..config import get_config, load_config, AppConfig
from ..db import Database
from ..db.models import IdolProfile, IdolType, IdolStatus, TrustedAccount, IdolKeywordEntry
from ..core.orchestrator import run_scrape_and_download

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

log_queue: queue.Queue = queue.Queue(maxsize=1000)
active_jobs: Dict[str, Any] = {"running": False, "target": None, "report": None, "status": "", "total": 0, "completed": 0}
_db_lock = asyncio.Lock()


def _log_sink(message):
    try:
        log_queue.put_nowait(message)
    except queue.Full:
        try:
            log_queue.get_nowait()
            log_queue.put_nowait(message)
        except Exception:
            pass


logger_handler_id = logger.add(_log_sink, format="{time:HH:mm:ss} | {level: <7} | {message}")


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    db_path = Path(cfg.general.download_dir) / "catchido.db"
    async with Database(db_path) as db:
        await db.initialize()
    logger.info("Catchido Web Server started")

    browser_thread = threading.Thread(target=_open_browser, daemon=True)
    browser_thread.start()

    scrape_task = asyncio.create_task(_periodic_scrape_loop())

    yield

    scrape_task.cancel()
    logger.remove(logger_handler_id)


def _open_browser():
    import time
    import webbrowser
    time.sleep(1.0)
    webbrowser.open("http://localhost:8000")


async def _periodic_scrape_loop():
    logger.info("Periodic background scraper loop initialized.")
    await asyncio.sleep(10)
    while True:
        try:
            cfg = get_config()
            interval = getattr(cfg.general, "auto_scrape_interval_hours", 0)
            if interval > 0:
                logger.info("Triggering auto-scrape (every {} hours) for all idols...", interval)
                db_path = Path(cfg.general.download_dir) / "catchido.db"
                async with Database(db_path) as db:
                    idols = await db.list_idols()

                for idol in idols:
                    if active_jobs["running"]:
                        logger.warning("Auto-scrape for {} skipped — another job running.", idol.display_name)
                        continue
                    try:
                        await _run_download_job(idol.display_name)
                    except Exception as ex:
                        logger.error("Failed auto-scraping for {}: {}", idol.display_name, ex)

                await asyncio.sleep(interval * 3600)
            else:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic auto-scrape loop: {}", e)
            await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Catchido API", version="0.2.0", lifespan=lifespan)

# Restrict CORS to localhost only
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Basic auth middleware
# ---------------------------------------------------------------------------

AUTH_TOKEN: Optional[str] = None


def _get_auth_token() -> Optional[str]:
    global AUTH_TOKEN
    if AUTH_TOKEN is not None:
        return AUTH_TOKEN
    cfg = get_config()
    token = getattr(cfg.general, "auth_token", None)
    if token:
        AUTH_TOKEN = str(token)
    return AUTH_TOKEN


async def require_auth(request: Request):
    required = _get_auth_token()
    if not required:
        return
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = auth_header
    if token != required:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Pydantic schemas (input validation)
# ---------------------------------------------------------------------------

class IdolSchema(BaseModel):
    name: str
    type: str  # "jp" or "kr"
    kanji: Optional[str] = None
    generation: Optional[str] = None
    team: Optional[str] = None
    hangul: Optional[str] = None
    stage_name: Optional[str] = None
    real_name: Optional[str] = None
    positions: Optional[List[str]] = []
    group: Optional[str] = None
    company: Optional[str] = None
    fandom: Optional[str] = None
    birthday: Optional[str] = None
    debut: Optional[str] = None
    status: Optional[str] = "active"
    graduation_date: Optional[str] = None
    nicknames: Optional[str] = ""
    exclude: Optional[str] = ""
    download_dir: Optional[str] = None
    twitter: Optional[List[str]] = []
    weibo: Optional[List[str]] = []
    instagram: Optional[List[str]] = []
    threads: Optional[List[str]] = []
    tiktok: Optional[List[str]] = []

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("jp", "kr"):
            raise ValueError("type must be 'jp' or 'kr'")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"active", "graduated", "hiatus", "disbanded", "solo", "left"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class DownloadRequest(BaseModel):
    depth: str = "recent"

    @field_validator("depth")
    @classmethod
    def validate_depth(cls, v: str) -> str:
        if v not in ("recent", "full"):
            raise ValueError("depth must be 'recent' or 'full'")
        return v


class SourceAccountSchema(BaseModel):
    platform: str
    username: str

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"twitter", "instagram", "threads", "tiktok", "weibo"}
        if v not in allowed:
            raise ValueError(f"platform must be one of {allowed}")
        return v


class ConfigUpdateSchema(BaseModel):
    download_dir: Optional[str] = None
    max_concurrent_downloads: Optional[int] = None
    auto_dedup: Optional[bool] = None
    dedup_threshold: Optional[int] = None
    prefer_higher_res: Optional[bool] = None
    download_photos: Optional[bool] = None
    download_videos: Optional[bool] = None
    auto_scrape_interval_hours: Optional[int] = None
    # Search
    min_relevance_score: Optional[float] = None
    auto_discover_accounts: Optional[bool] = None
    auto_generate_keywords: Optional[bool] = None
    include_fan_content: Optional[bool] = None
    exclude_fanart: Optional[bool] = None
    # Proxy
    proxy_enabled: Optional[bool] = None
    proxy_http: Optional[str] = None
    proxy_https: Optional[str] = None
    # Twitter
    include_retweets: Optional[bool] = None
    twitter_request_delay: Optional[int] = None
    # Scraper delays
    ig_request_delay: Optional[int] = None
    threads_request_delay: Optional[int] = None
    tiktok_request_delay: Optional[int] = None
    weibo_request_delay: Optional[int] = None
    # Credentials — write-only, never read back
    twitter_bearer: Optional[str] = None
    weibo_cookie: Optional[str] = None
    instagram_cookie: Optional[str] = None
    threads_cookie: Optional[str] = None
    tiktok_cookie: Optional[str] = None

    @field_validator("download_dir")
    @classmethod
    def validate_download_dir(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("download_dir cannot be empty")
        return v

    @field_validator("max_concurrent_downloads")
    @classmethod
    def validate_concurrency(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 50):
            raise ValueError("max_concurrent_downloads must be between 1 and 50")
        return v


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    cfg = get_config()
    return Path(cfg.general.download_dir) / "catchido.db"


# ---------------------------------------------------------------------------
# API Routes — Read-only (no auth required for local usage)
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats():
    async with Database(_db_path()) as db:
        stats_data = await db.get_download_stats()
        idols = await db.list_idols()
    return {
        "total_idols": len(idols),
        "total_count": stats_data.get("total_count", 0),
        "total_size": stats_data.get("total_size", 0),
        "platforms": stats_data.get("platforms", {}),
        "is_job_running": active_jobs["running"],
        "active_job_target": active_jobs["target"],
    }


@app.get("/api/idols")
async def get_idols():
    async with Database(_db_path()) as db:
        idols = await db.list_idols()
        result = []
        for idol in idols:
            media_count = await db.get_media_count(idol.display_name)
            result.append({
                "name": idol.display_name,
                "type": idol.idol_type.value,
                "group": idol.group_name or "Solo",
                "company": idol.company or "-",
                "status": idol.status.value,
                "media_count": media_count,
            })
    return result


@app.get("/api/idols/{name}")
async def get_idol_detail(name: str):
    async with Database(_db_path()) as db:
        idol = await db.get_idol(name)
        if not idol:
            raise HTTPException(status_code=404, detail="Idol not found")
        keywords = await db.get_keywords_for_idol(name)
        trusted = await db.get_trusted_accounts(name)
        media_count = await db.get_media_count(name)
    return {
        "profile": {
            "name": idol.display_name,
            "type": idol.idol_type.value,
            "kanji": idol.kanji_name,
            "generation": idol.generation,
            "team": idol.team,
            "hangul": idol.hangul_name,
            "stage_name": idol.stage_name,
            "real_name": idol.real_name,
            "positions": idol.positions,
            "group": idol.group_name,
            "company": idol.company,
            "fandom": idol.fandom_name,
            "birthday": idol.birthday,
            "debut": idol.debut_date,
            "status": idol.status.value,
            "graduation_date": idol.graduation_date,
            "download_dir": idol.download_dir,
            "media_count": media_count,
        },
        "sources": [
            {"platform": t.platform, "username": t.username, "type": t.account_type}
            for t in trusted
        ],
        "keywords": [k.keyword for k in keywords],
    }


@app.get("/api/idols/{name}/media")
async def get_idol_media(name: str, limit: int = 50, offset: int = 0):
    cfg = get_config()
    async with Database(_db_path()) as db:
        async with db._conn.execute(
            "SELECT COUNT(*) FROM media_hashes WHERE idol_name = ?", (name,)
        ) as c:
            total = (await c.fetchone())[0]
        async with db._conn.execute(
            "SELECT id, file_path, source_platform, source_url, downloaded_at, source_user "
            "FROM media_hashes WHERE idol_name = ? ORDER BY downloaded_at DESC LIMIT ? OFFSET ?",
            (name, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        idol = await db.get_idol(name)

    media_list = []
    bases = [Path(cfg.general.download_dir)]
    if idol and idol.download_dir:
        bases.insert(0, Path(idol.download_dir))
    for r in rows:
        path_str = r["file_path"]
        try:
            fp = Path(path_str)
            rel_path = None
            if not fp.is_absolute():
                rel_path = fp
            else:
                for b in bases:
                    try:
                        rel_path = fp.relative_to(b)
                        break
                    except ValueError:
                        continue
                if rel_path is None:
                    rel_path = Path(fp.name)
            url_str = r["source_url"] or ""
            post_id = Path(path_str).stem
            if url_str:
                import re
                match = re.search(r'/([^/?]+)', url_str)
                if match:
                    post_id = match.group(1)[:16]
            media_list.append({
                "id": r["id"],
                "src": f"/media/{quote(rel_path.as_posix())}",
                "platform": r["source_platform"],
                "post_id": post_id,
                "created_at": r["downloaded_at"],
                "caption": f"Downloaded from {r['source_user'] or 'unknown'}",
            })
        except Exception:
            pass
    return {"items": media_list, "total": total, "limit": limit, "offset": offset}


@app.get("/api/logs")
async def get_logs():
    logs = []
    while not log_queue.empty():
        logs.append(log_queue.get())
    return logs


@app.get("/api/config")
async def get_web_config():
    """Return config fields including credentials (local-only app, no remote exposure)."""
    c = get_config()
    return {
        "download_dir": c.general.download_dir,
        "max_concurrent_downloads": c.general.max_concurrent_downloads,
        "auto_dedup": c.general.auto_dedup,
        "dedup_threshold": c.general.dedup_threshold,
        "prefer_higher_res": c.general.prefer_higher_res,
        "download_photos": c.general.download_photos,
        "download_videos": c.general.download_videos,
        "auto_scrape_interval_hours": getattr(c.general, "auto_scrape_interval_hours", 0),
        "min_relevance_score": c.search.min_relevance_score,
        "auto_discover_accounts": c.search.auto_discover_accounts,
        "auto_generate_keywords": c.search.auto_generate_keywords,
        "include_fan_content": c.search.include_fan_content,
        "exclude_fanart": c.search.exclude_fanart,
        "proxy_enabled": c.proxy.enabled,
        "proxy_http": c.proxy.http,
        "proxy_https": c.proxy.https,
        "include_retweets": c.twitter.include_retweets,
        "twitter_request_delay": c.twitter.request_delay,
        "ig_request_delay": c.instagram.request_delay,
        "threads_request_delay": c.threads.request_delay,
        "tiktok_request_delay": c.tiktok.request_delay,
        "weibo_request_delay": c.weibo.request_delay,
        "twitter_bearer": _clean_undef(c.twitter.bearer_token),
        "weibo_cookie": _clean_undef(c.weibo.cookie),
        "instagram_cookie": _clean_undef(c.instagram.session_cookie),
        "threads_cookie": _clean_undef(c.threads.session_cookie),
        "tiktok_cookie": _clean_undef(c.tiktok.session_cookie),
    }


# ---------------------------------------------------------------------------
# API Routes — Mutations (auth required)
# ---------------------------------------------------------------------------

@app.post("/api/idols", dependencies=[Depends(require_auth)])
async def add_idol(data: IdolSchema):
    # Create per-idol download folder
    cfg = get_config()
    base_dir = Path(cfg.general.download_dir)
    idol_dir = base_dir / data.name
    idol_dir.mkdir(parents=True, exist_ok=True)

    profile = IdolProfile(
        display_name=data.name,
        idol_type=IdolType(data.type),
        kanji_name=data.kanji,
        generation=data.generation,
        team=data.team,
        hangul_name=data.hangul,
        stage_name=data.stage_name,
        real_name=data.real_name,
        positions=data.positions or [],
        group_name=data.group,
        company=data.company,
        fandom_name=data.fandom,
        birthday=data.birthday,
        debut_date=data.debut,
        status=IdolStatus(data.status or "active"),
        graduation_date=data.graduation_date,
        download_dir=data.download_dir or str(idol_dir),
    )

    async with Database(_db_path()) as db:
        success = await db.add_idol(profile)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add idol profile")

        await _register_sources(db, data.name, data)
        await _generate_and_save_keywords(db, profile, data)

    return {"status": "ok", "message": f"Idol {data.name} added successfully"}


@app.put("/api/idols/{name}", dependencies=[Depends(require_auth)])
async def update_idol(name: str, data: IdolSchema):
    profile = IdolProfile(
        display_name=data.name,
        idol_type=IdolType(data.type),
        kanji_name=data.kanji,
        generation=data.generation,
        team=data.team,
        hangul_name=data.hangul,
        stage_name=data.stage_name,
        real_name=data.real_name,
        positions=data.positions or [],
        group_name=data.group,
        company=data.company,
        fandom_name=data.fandom,
        birthday=data.birthday,
        debut_date=data.debut,
        status=IdolStatus(data.status or "active"),
        graduation_date=data.graduation_date,
        download_dir=data.download_dir,
    )

    async with Database(_db_path()) as db:
        success = await db.update_idol(name, profile)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update idol profile")

        has_sources = any([data.twitter, data.weibo, data.instagram, data.threads, data.tiktok])
        if has_sources:
            await db.delete_trusted_accounts_for_idol(data.name)
            await _register_sources(db, data.name, data)

    return {"status": "ok", "message": f"Idol {data.name} updated successfully"}


@app.delete("/api/idols/{name}", dependencies=[Depends(require_auth)])
async def delete_idol(name: str):
    async with Database(_db_path()) as db:
        await db.delete_idol(name)
    return {"status": "ok", "message": f"Idol {name} deleted"}


@app.post("/api/idols/{name}/sources", dependencies=[Depends(require_auth)])
async def add_source(name: str, data: SourceAccountSchema):
    async with Database(_db_path()) as db:
        idol = await db.get_idol(name)
        if not idol:
            raise HTTPException(status_code=404, detail="Idol not found")
        username = _extract_username(data.username, data.platform)
        if not username:
            raise HTTPException(status_code=400, detail="Invalid username or URL")
        await db.add_trusted_account(TrustedAccount(
            idol_name=name,
            platform=data.platform,
            username=username,
            account_type="official" if username.lower() == f"@{name.lower()}" else "fansite",
        ))
    return {"status": "ok", "message": f"Source @{username} added to {name}"}


@app.delete("/api/idols/{name}/sources", dependencies=[Depends(require_auth)])
async def remove_source(name: str, platform: str, username: str):
    async with Database(_db_path()) as db:
        await db._conn.execute(
            "DELETE FROM trusted_accounts WHERE idol_name = ? AND platform = ? AND username = ?",
            (name, platform, username),
        )
        await db._conn.commit()
    return {"status": "ok", "message": f"Source {username} removed from {name}"}


@app.post("/api/idols/{name}/download", dependencies=[Depends(require_auth)])
async def trigger_download(name: str, req: DownloadRequest, background_tasks: BackgroundTasks):
    if active_jobs["running"]:
        raise HTTPException(status_code=400, detail="Another download job is already running")
    active_jobs["status"] = "queued"
    background_tasks.add_task(_run_download_job, name, req.depth)
    return {"status": "ok", "message": f"Download triggered for {name} (depth: {req.depth})"}


@app.get("/api/download-progress")
async def get_download_progress():
    return {k: active_jobs[k] for k in ("running", "target", "status", "total", "completed")}


@app.delete("/api/media/{media_id}")
async def delete_media(media_id: int):
    async with Database(_db_path()) as db:
        async with db._conn.execute(
            "SELECT file_path FROM media_hashes WHERE id = ?", (media_id,)
        ) as c:
            row = await c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media not found")
        fp = Path(row["file_path"])
        await db._conn.execute("DELETE FROM media_hashes WHERE id = ?", (media_id,))
        await db._conn.commit()
    if fp.exists():
        fp.unlink()
    return {"status": "ok", "message": "Media deleted"}


@app.post("/api/config", dependencies=[Depends(require_auth)])
async def save_web_config(data: ConfigUpdateSchema):
    config_file = Path("config.toml")
    if not config_file.exists():
        example = Path("config.example.toml")
        if example.exists():
            import shutil
            shutil.copy(example, config_file)
        else:
            config_file.write_text("", encoding="utf-8")

    # Read existing config to preserve fields not in the update
    try:
        existing = config_file.read_text(encoding="utf-8")
    except OSError:
        existing = ""

    # Build TOML manually for the fields we allow updating
    def _toml_str(v: str) -> str:
        v = v.replace("\\", "/")
        v = v.replace('"', '\\"')
        return f'"{v}"'

    cfg = get_config()

    lines = ["[general]"]
    dl_dir = data.download_dir if data.download_dir is not None else cfg.general.download_dir
    lines.append(f"download_dir = {_toml_str(dl_dir)}")

    max_dl = data.max_concurrent_downloads if data.max_concurrent_downloads is not None else cfg.general.max_concurrent_downloads
    lines.append(f"max_concurrent_downloads = {max_dl}")

    auto_dedup = data.auto_dedup if data.auto_dedup is not None else cfg.general.auto_dedup
    lines.append(f"auto_dedup = {str(auto_dedup).lower()}")

    dedup_t = data.dedup_threshold if data.dedup_threshold is not None else cfg.general.dedup_threshold
    lines.append(f"dedup_threshold = {dedup_t}")

    prefer = data.prefer_higher_res if data.prefer_higher_res is not None else cfg.general.prefer_higher_res
    lines.append(f"prefer_higher_res = {str(prefer).lower()}")

    dl_photos = data.download_photos if data.download_photos is not None else cfg.general.download_photos
    lines.append(f"download_photos = {str(dl_photos).lower()}")

    dl_vids = data.download_videos if data.download_videos is not None else cfg.general.download_videos
    lines.append(f"download_videos = {str(dl_vids).lower()}")

    auto_int = data.auto_scrape_interval_hours if data.auto_scrape_interval_hours is not None else getattr(cfg.general, "auto_scrape_interval_hours", 0)
    lines.append(f"auto_scrape_interval_hours = {auto_int}")

    lines.append("")

    # Search settings
    lines.append("[search]")
    val = data.min_relevance_score if data.min_relevance_score is not None else cfg.search.min_relevance_score
    lines.append(f"min_relevance_score = {val}")
    val = data.auto_discover_accounts if data.auto_discover_accounts is not None else cfg.search.auto_discover_accounts
    lines.append(f"auto_discover_accounts = {str(val).lower()}")
    val = data.auto_generate_keywords if data.auto_generate_keywords is not None else cfg.search.auto_generate_keywords
    lines.append(f"auto_generate_keywords = {str(val).lower()}")
    val = data.include_fan_content if data.include_fan_content is not None else cfg.search.include_fan_content
    lines.append(f"include_fan_content = {str(val).lower()}")
    val = data.exclude_fanart if data.exclude_fanart is not None else cfg.search.exclude_fanart
    lines.append(f"exclude_fanart = {str(val).lower()}")
    lines.append("")

    # Proxy settings
    lines.append("[proxy]")
    val = data.proxy_enabled if data.proxy_enabled is not None else cfg.proxy.enabled
    lines.append(f"enabled = {str(val).lower()}")
    val = data.proxy_http if data.proxy_http is not None else cfg.proxy.http
    lines.append(f'http = {_toml_str(val)}')
    val = data.proxy_https if data.proxy_https is not None else cfg.proxy.https
    lines.append(f'https = {_toml_str(val)}')
    lines.append("")

    # Credentials — only write if provided (never read back)
    bearer = _clean_undef(data.twitter_bearer if data.twitter_bearer is not None else cfg.twitter.bearer_token)
    lines.append("[twitter]")
    lines.append(f"bearer_token = {_toml_str(bearer)}")
    val = data.include_retweets if data.include_retweets is not None else cfg.twitter.include_retweets
    lines.append(f"include_retweets = {str(val).lower()}")
    val = data.twitter_request_delay if data.twitter_request_delay is not None else cfg.twitter.request_delay
    lines.append(f"request_delay = {val}")
    lines.append("")

    ig_cookie = _clean_undef(data.instagram_cookie if data.instagram_cookie is not None else cfg.instagram.session_cookie)
    lines.append("[instagram]")
    lines.append(f"session_cookie = {_toml_str(ig_cookie)}")
    val = data.ig_request_delay if data.ig_request_delay is not None else cfg.instagram.request_delay
    lines.append(f"request_delay = {val}")
    lines.append("")

    th_cookie = _clean_undef(data.threads_cookie if data.threads_cookie is not None else cfg.threads.session_cookie)
    lines.append("[threads]")
    lines.append(f"session_cookie = {_toml_str(th_cookie)}")
    val = data.threads_request_delay if data.threads_request_delay is not None else cfg.threads.request_delay
    lines.append(f"request_delay = {val}")
    lines.append("")

    tk_cookie = _clean_undef(data.tiktok_cookie if data.tiktok_cookie is not None else cfg.tiktok.session_cookie)
    lines.append("[tiktok]")
    lines.append(f"session_cookie = {_toml_str(tk_cookie)}")
    val = data.tiktok_request_delay if data.tiktok_request_delay is not None else cfg.tiktok.request_delay
    lines.append(f"request_delay = {val}")
    lines.append("")

    wb_cookie = _clean_undef(data.weibo_cookie if data.weibo_cookie is not None else cfg.weibo.cookie)
    lines.append("[weibo]")
    lines.append(f"cookie = {_toml_str(wb_cookie)}")
    val = data.weibo_request_delay if data.weibo_request_delay is not None else cfg.weibo.request_delay
    lines.append(f"request_delay = {val}")

    try:
        config_file.write_text("\n".join(lines), encoding="utf-8")
        load_config("config.toml")
        return {"status": "ok", "message": "Configuration saved successfully"}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config.toml: {e}")


@app.post("/api/utils/test-cookies")
async def validate_cookies(data: Dict[str, str]):
    """Test cookie validity without persisting anything."""
    import httpx
    results = {}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    ig_cookie = data.get("instagram_cookie", "")
    if ig_cookie:
        try:
            headers = {
                "Cookie": f"sessionid={ig_cookie}",
                "User-Agent": "Instagram 291.0.0.18.111 Android",
                "X-IG-App-ID": "936619743392459",
            }
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                res = await client.get("https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram", headers=headers)
                if res.status_code == 200:
                    results["instagram"] = {"status": "ok", "message": "Valid (Active)"}
                elif res.status_code == 429:
                    results["instagram"] = {"status": "ok", "message": "Valid (Active) — rate limited"}
                elif res.status_code in (301, 302):
                    results["instagram"] = {"status": "error", "message": "Invalid (Session expired)"}
                else:
                    results["instagram"] = {"status": "error", "message": f"Invalid (Status {res.status_code})"}
        except Exception as e:
            results["instagram"] = {"status": "error", "message": f"Failed: {e}"}
    else:
        results["instagram"] = {"status": "empty", "message": "Not configured"}

    wb_cookie = data.get("weibo_cookie", "")
    if wb_cookie:
        try:
            headers = {"Cookie": wb_cookie, "User-Agent": ua, "Referer": "https://m.weibo.cn/"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://m.weibo.cn/api/config", headers=headers)
                if res.status_code == 200:
                    is_login = res.json().get("data", {}).get("isLogin", False)
                    results["weibo"] = (
                        {"status": "ok", "message": "Valid (Logged in)"}
                        if is_login
                        else {"status": "error", "message": "Invalid (Not logged in)"}
                    )
                else:
                    results["weibo"] = {"status": "error", "message": f"Failed (Status {res.status_code})"}
        except Exception as e:
            results["weibo"] = {"status": "error", "message": f"Failed: {e}"}
    else:
        results["weibo"] = {"status": "empty", "message": "Not configured"}

    tk_cookie = data.get("tiktok_cookie", "")
    if tk_cookie:
        try:
            headers = {"Cookie": f"sessionid={tk_cookie}", "User-Agent": ua}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://www.tiktok.com/api/user/profile/self/", headers=headers)
                if res.status_code == 200:
                    data_json = res.json()
                    user = data_json.get("userInfo", {}).get("user", {})
                    if user.get("uniqueId"):
                        results["tiktok"] = {"status": "ok", "message": f"Valid ({user['uniqueId']})"}
                    else:
                        results["tiktok"] = {"status": "error", "message": "Invalid (no user data)"}
                else:
                    results["tiktok"] = {"status": "error", "message": f"Invalid (Status {res.status_code})"}
        except Exception as e:
            results["tiktok"] = {"status": "error", "message": f"Failed: {e}"}
    else:
        results["tiktok"] = {"status": "empty", "message": "Not configured"}

    th_cookie = data.get("threads_cookie", "")
    if th_cookie:
        try:
            headers = {"Cookie": f"sessionid={th_cookie}", "User-Agent": ua}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get("https://www.threads.net/api/graphql", headers=headers, params={"variables": "{}", "doc_id": "17888483320059182"})
                if res.status_code == 200:
                    results["threads"] = {"status": "ok", "message": "Valid (Active)"}
                else:
                    results["threads"] = {"status": "error", "message": f"Invalid (Status {res.status_code})"}
        except Exception as e:
            results["threads"] = {"status": "error", "message": f"Failed: {e}"}
    else:
        results["threads"] = {"status": "empty", "message": "Not configured"}

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_undef(val: str | None) -> str:
    """Return empty string for None, 'undefined', or whitespace-only values."""
    if not val or val.strip().lower() in ("undefined", "none", ""):
        return ""
    return val


def _extract_username(raw: str, platform: str) -> str:
    """Extract username from a URL or plain text. Handles links and @mentions."""
    import re
    raw = raw.strip()

    if not raw:
        return ""

    # Strip @ prefix
    if raw.startswith("@"):
        return raw[1:]

    # If it's a URL, extract the username from the path
    if "http" in raw.lower() or "/" in raw:
        patterns = {
            "instagram": r"instagram\.com/([A-Za-z0-9_.]+)",
            "twitter": r"(?:twitter|x)\.com/([A-Za-z0-9_]+)",
            "threads": r"threads\.net/@?([A-Za-z0-9_.]+)",
            "tiktok": r"tiktok\.com/@([A-Za-z0-9_.]+)",
            "weibo": r"weibo\.com/u/(\d+)",
        }
        pattern = patterns.get(platform, r"/([A-Za-z0-9_]+)$")
        match = re.search(pattern, raw)
        if match:
            return match.group(1)

    # Plain text — return as-is (strip any remaining whitespace)
    return raw


async def _register_sources(db: Database, idol_name: str, data: IdolSchema):
    platform_sources = [
        ("twitter", data.twitter),
        ("weibo", data.weibo),
        ("instagram", data.instagram),
        ("threads", data.threads),
        ("tiktok", data.tiktok),
    ]
    for platform_name, accounts in platform_sources:
        if accounts:
            for acct in accounts:
                acct_clean = acct.strip()
                if acct_clean:
                    await db.add_trusted_account(TrustedAccount(
                        idol_name=idol_name,
                        platform=platform_name,
                        username=acct_clean,
                        account_type="official" if acct_clean.lower() == f"@{idol_name.lower()}" else "fansite",
                    ))


async def _generate_and_save_keywords(db: Database, profile: IdolProfile, data: IdolSchema):
    from ..keywords.expander import KeywordExpander

    expander = KeywordExpander()
    exclude_list = (
        [e.strip() for e in data.exclude.split(",") if e.strip()]
        if data.exclude
        else ["cosplay", "fanart", "AI생성"]
    )
    nicknames_list = (
        [n.strip() for n in data.nicknames.split(",") if n.strip()]
        if data.nicknames
        else []
    )

    raw_profile = {
        "name": data.name,
        "idol_type": data.type,
        "profile": {
            "kanji_name": data.kanji,
            "hangul_name": data.hangul,
            "stage_name": data.stage_name,
            "real_name": data.real_name,
            "group": data.group,
            "birthday": data.birthday,
        },
        "keywords": {
            "nicknames": nicknames_list,
            "exclude": exclude_list,
        },
    }

    expanded = expander.expand_profile(raw_profile)
    for kw in expanded.search_keywords:
        await db.add_keyword(IdolKeywordEntry(
            idol_name=data.name, idol_type=profile.idol_type,
            keyword=kw, script_type="generated", platform="all", is_auto_generated=True,
        ))
    for ht in expanded.hashtags:
        await db.add_keyword(IdolKeywordEntry(
            idol_name=data.name, idol_type=profile.idol_type,
            keyword=ht, script_type="hashtag", platform="all", is_auto_generated=True,
        ))
    await db.add_keyword(IdolKeywordEntry(
        idol_name=data.name, idol_type=profile.idol_type,
        keyword=data.name, script_type="alias", platform="all", is_auto_generated=True,
    ))
    await db.add_keyword(IdolKeywordEntry(
        idol_name=data.name, idol_type=profile.idol_type,
        keyword=f"#{data.name}", script_type="hashtag", platform="all", is_auto_generated=True,
    ))


async def _run_download_job(target: str, depth: str = "recent"):
    active_jobs["running"] = True
    active_jobs["target"] = target
    active_jobs["report"] = None
    active_jobs["status"] = "starting"
    active_jobs["total"] = 0
    active_jobs["completed"] = 0
    try:
        cfg = get_config()
        db_path = Path(cfg.general.download_dir) / "catchido.db"
        async with Database(db_path) as db:
            if target == "ALL":
                targets = await db.list_idols()
            else:
                idol = await db.get_idol(target)
                targets = [idol] if idol else []

            if not targets:
                logger.warning("No scrape targets found.")
                return

            active_jobs["status"] = "scraping"
            await run_scrape_and_download(db, cfg, targets, depth=depth)
    except Exception as e:
        logger.exception("Error in background download job: {}", e)
    finally:
        active_jobs["running"] = False
        active_jobs["target"] = None
        active_jobs["status"] = "done"


# ---------------------------------------------------------------------------
# Dynamic media serving (respects config changes without restart)
# ---------------------------------------------------------------------------

@app.get("/media/{path:path}")
async def serve_media(path: str):
    cfg = get_config()
    decoded = unquote(path)
    file_path = Path(cfg.general.download_dir) / decoded
    if not file_path.exists() or not file_path.is_file():
        # fallback: try looking up in media_hashes
        async with Database(_db_path()) as db:
            async with db._conn.execute(
                "SELECT file_path FROM media_hashes WHERE file_path LIKE ? LIMIT 1",
                (f"%/{decoded}",),
            ) as c:
                row = await c.fetchone()
            if row:
                alt = Path(row["file_path"])
                if alt.exists() and alt.is_file():
                    return FileResponse(alt)
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def get_index():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Catchido Web GUI frontend files missing. Please check src/catchido/web/static/"}


def run_server(host="localhost", port=8000):
    import uvicorn
    uvicorn.run("catchido.web.server:app", host=host, port=port, reload=False)
