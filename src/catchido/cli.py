import sys
import asyncio
import click
from pathlib import Path
from typing import List

# Fix Windows terminal encoding issues
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .config import load_config
from .utils.logger import setup_logger
from .db import Database
from .db.models import IdolProfile, IdolType, IdolStatus, TrustedAccount, IdolKeywordEntry, MediaItem
from .keywords.expander import KeywordExpander
from .scrapers.twitter import TwitterScraper
from .scrapers.weibo import WeiboScraper
from .scrapers.instagram import InstagramScraper
from .scrapers.threads import ThreadsScraper
from .scrapers.tiktok import TikTokScraper
from .core.downloader import DownloadManager
from .core.dedup import DedupEngine
from .core.organizer import FileOrganizer
from .core.orchestrator import run_scrape_and_download

console = Console()

# Tying async execution with click
def coro(f):
    import functools
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.group()
@click.option("--config-file", "-c", type=click.Path(), help="Path to config.toml")
@click.pass_context
def cli(ctx, config_file):
    """🎯 Catchido — Smart HD Idol Media Scraper & Organizer"""
    # Load config
    cfg = load_config(config_file)
    
    # Initialize logger
    setup_logger(cfg.general.log_file, cfg.general.log_level)
    
    # Set up DB connection info
    db_path = Path(cfg.general.download_dir) / "catchido.db"
    ctx.obj = {
        "config": cfg,
        "db_path": db_path
    }

@cli.command()
@click.pass_context
@coro
async def init(ctx):
    """Initialize database and config template."""
    db_path = ctx.obj["db_path"]
    
    console.print(f"[bold green]Initializing Catchido...[/bold green]")
    
    # Init DB
    async with Database(db_path) as db:
        await db.initialize()
    
    console.print(f"[green][OK][/green] Database initialized at: [cyan]{db_path}[/cyan]")
    
    # Create default config.toml if it doesn't exist
    config_file = Path("config.toml")
    if not config_file.exists():
        example_file = Path("config.example.toml")
        if example_file.exists():
            import shutil
            shutil.copy(example_file, config_file)
            console.print(f"[green][OK][/green] Default config.toml created from template.")
        else:
            # Write minimal config
            config_file.write_text("""[general]
download_dir = "C:\\Users\\YourName\\Pictures\\Catchido"
max_concurrent_downloads = 5
auto_dedup = true
prefer_higher_res = true
download_photos = true
download_videos = false

[twitter]
bearer_token = ""

[instagram]
session_cookie = ""

[threads]
session_cookie = ""

[tiktok]
session_cookie = ""

[weibo]
cookie = ""
""")
            console.print(f"[green][OK][/green] Minimal config.toml created.")
            
    console.print("[bold green]Initialization completed successfully![/bold green]")

@cli.command()
@click.argument("name")
@click.option("--type", "idol_type_str", type=click.Choice(["jp", "kr"]), default="jp", help="Idol type (jp/kr)")
# JP specific options
@click.option("--kanji", help="JP: Kanji name representation")
@click.option("--generation", help="JP: Group intake generation")
@click.option("--team", help="JP: Team name")
# KR specific options
@click.option("--hangul", help="KR: Hangul name representation")
@click.option("--stage-name", help="KR: Stage name")
@click.option("--real-name", help="KR: Real name")
@click.option("--position", help="KR: Positions (comma separated)")
# Group Info
@click.option("--group", help="Group name")
@click.option("--company", help="Entertainment agency / company")
@click.option("--fandom", help="Fandom name")
# Personal Info
@click.option("--birthday", help="Birthday (YYYY-MM-DD)")
@click.option("--debut", help="Debut date (YYYY-MM-DD)")
@click.option("--status", type=click.Choice(["active", "graduated", "hiatus", "solo", "left"]), default="active", help="Idol status")
@click.option("--graduation-date", help="JP: Graduation date (YYYY-MM-DD)")
# Extra metadata
@click.option("--nicknames", help="Nicknames (comma separated)")
# Sources — all 5 platforms
@click.option("--twitter", "twitters", multiple=True, help="Twitter fanaccount or official username")
@click.option("--weibo", "weibos", multiple=True, help="Weibo fanaccount or official ID")
@click.option("--instagram", "instagrams", multiple=True, help="Instagram fanaccount or official username")
@click.option("--threads", "threads_accounts", multiple=True, help="Threads fanaccount or official username")
@click.option("--tiktok", "tiktoks", multiple=True, help="TikTok fanaccount or official username")
# Filters
@click.option("--exclude", help="Exclude terms (comma separated)")
@click.pass_context
@coro
async def add(ctx, name, idol_type_str, kanji, generation, team, hangul, stage_name, real_name, position,
              group, company, fandom, birthday, debut, status, graduation_date, nicknames,
              twitters, weibos, instagrams, threads_accounts, tiktoks, exclude):
    """Add a new idol/bias to track in database."""
    db_path = ctx.obj["db_path"]
    
    positions_list = [p.strip() for p in position.split(",") if p.strip()] if position else []
    
    profile = IdolProfile(
        display_name=name,
        idol_type=IdolType(idol_type_str),
        kanji_name=kanji,
        generation=generation,
        team=team,
        hangul_name=hangul,
        stage_name=stage_name,
        real_name=real_name,
        positions=positions_list,
        group_name=group,
        company=company,
        fandom_name=fandom,
        birthday=birthday,
        debut_date=debut,
        status=IdolStatus(status),
        graduation_date=graduation_date
    )

    async with Database(db_path) as db:
        # Check if already exists
        existing = await db.get_idol(name)
        if existing:
            if not click.confirm(f"Idol '{name}' already exists. Overwrite?"):
                return
                
        # Save profile
        success = await db.add_idol(profile)
        if not success:
            console.print("[red]Failed to save idol profile.[/red]")
            return
            
        # Register sources — all 5 platforms
        platform_sources = [
            ("twitter", twitters),
            ("weibo", weibos),
            ("instagram", instagrams),
            ("threads", threads_accounts),
            ("tiktok", tiktoks),
        ]
        
        for platform_name, accounts in platform_sources:
            for acct in accounts:
                acct_clean = acct.strip()
                if acct_clean:
                    await db.add_trusted_account(TrustedAccount(
                        idol_name=name,
                        platform=platform_name,
                        username=acct_clean,
                        account_type="official" if acct_clean.lower() == f"@{name.lower()}" else "fansite"
                    ))

        # Auto-generate keywords
        expander = KeywordExpander()
        exclude_list = [e.strip() for e in exclude.split(",") if e.strip()] if exclude else ["cosplay", "fanart", "AI생성"]
        
        # Build raw dict for keyword expander logic
        raw_profile = {
            "name": name,
            "idol_type": idol_type_str,
            "profile": {
                "kanji_name": kanji,
                "hangul_name": hangul,
                "stage_name": stage_name,
                "real_name": real_name,
                "group": group,
                "birthday": birthday
            },
            "keywords": {
                "nicknames": [n.strip() for n in nicknames.split(",") if n.strip()] if nicknames else [],
                "exclude": exclude_list
            }
        }
        
        expanded = expander.expand_profile(raw_profile)
        
        # Save generated keywords to database
        for kw in expanded.search_keywords:
            await db.add_keyword(IdolKeywordEntry(
                idol_name=name,
                idol_type=profile.idol_type,
                keyword=kw,
                script_type="generated",
                platform="all",
                is_auto_generated=True
            ))
            
        # Add generated hashtags
        for ht in expanded.hashtags:
            await db.add_keyword(IdolKeywordEntry(
                idol_name=name,
                idol_type=profile.idol_type,
                keyword=ht,
                script_type="hashtag",
                platform="all",
                is_auto_generated=True
            ))

        console.print(f"[bold green]Successfully added {name} to tracking! ({len(expanded.search_keywords)} keywords generated)[/bold green]")

@cli.command()
@click.argument("name", required=False)
@click.option("--all", "download_all", is_flag=True, help="Download all tracked idols")
@click.option("--group", "group_filter", help="Download all members in specific group")
@click.option("--limit", type=int, help="Limit number of posts per source")
@click.option("--since", help="Minimum post ID checkpoint to check (skip earlier)")
@click.option("--depth", type=click.Choice(["recent", "full"]), default="recent", help="Scrape depth")
@click.pass_context
@coro
async def download(ctx, name, download_all, group_filter, limit, since, depth):
    """Scrape and download HD photos/videos for tracked idols."""
    config = ctx.obj["config"]
    db_path = ctx.obj["db_path"]

    # 1. Collect targets to download
    targets: List[IdolProfile] = []
    async with Database(db_path) as db:
        if download_all:
            targets = await db.list_idols()
        elif group_filter:
            targets = await db.list_by_group(group_filter)
        else:
            if not name:
                console.print("[red]Error: Please specify an idol name or use --all / --group options.[/red]")
                return
            idol = await db.get_idol(name)
            if idol:
                targets = [idol]
            else:
                console.print(f"[red]Idol '{name}' not found in database.[/red]")
                return

        if not targets:
            console.print("[yellow]No idols matched criteria.[/yellow]")
            return

        console.print(Panel(f"[bold green]Starting Scrape Session ({len(targets)} idol(s))[/bold green]"))

        # Auto-reorganize existing files to split photos and videos
        organizer = FileOrganizer(config.general.download_dir)
        reorg_res = organizer.reorganize_existing_files()
        moved_list = reorg_res.get("moved", [])
        if moved_list:
            async with db._conn.cursor() as cursor:
                for old_p, new_p in moved_list:
                    await cursor.execute("UPDATE media_hashes SET file_path = ? WHERE file_path = ?", (new_p, old_p))
            await db._conn.commit()

        # Use shared orchestrator
        await run_scrape_and_download(db, config, targets, depth=depth)

        console.print(f"[bold green]Scrape session completed![/bold green]")

@cli.command()
@click.argument("url")
@click.option("--idol", "idol_name", help="Associate grabbed media with this idol profile")
@click.pass_context
@coro
async def grab(ctx, url, idol_name):
    """Directly download media from a specific post URL."""
    config = ctx.obj["config"]
    db_path = ctx.obj["db_path"]
    
    console.print(f"Analyzing URL: [cyan]{url}[/cyan]")
    
    # Identify platform
    platform = None
    if "twitter.com" in url or "x.com" in url:
        platform = "twitter"
    elif "weibo.com" in url or "weibo.cn" in url:
        platform = "weibo"
    elif "instagram.com" in url:
        platform = "instagram"
    elif "threads.net" in url:
        platform = "threads"
    elif "tiktok.com" in url:
        platform = "tiktok"
    else:
        console.print("[red]Unsupported URL platform. Supported: Twitter/X, Instagram, Threads, TikTok, Weibo.[/red]")
        return

    items = []
    # Scrape Single Post
    if platform == "twitter":
        tw_scraper = TwitterScraper(config.twitter.bearer_token, config)
        items = await tw_scraper.fetch_media_from_url(url)
        await tw_scraper.close()
    elif platform == "weibo":
        wb_scraper = WeiboScraper(config.weibo.cookie, config)
        items = await wb_scraper.fetch_media_from_url(url)
        await wb_scraper.close()
    elif platform == "instagram":
        ig_scraper = InstagramScraper(config.instagram.session_cookie, config)
        items = await ig_scraper.fetch_media_from_url(url)
        await ig_scraper.close()
    elif platform == "threads":
        th_scraper = ThreadsScraper(config.threads.session_cookie, config)
        items = await th_scraper.fetch_media_from_url(url)
        await th_scraper.close()
    elif platform == "tiktok":
        tk_scraper = TikTokScraper(config.tiktok.session_cookie, config)
        items = await tk_scraper.fetch_media_from_url(url)
        await tk_scraper.close()

    if not items:
        console.print("[red]No media found in the post URL.[/red]")
        return
        
    console.print(f"Found {len(items)} media item(s).")

    # Downloader needs an IdolProfile context. If none provided, create temporary default
    async with Database(db_path) as db:
        idol = None
        if idol_name:
            idol = await db.get_idol(idol_name)
        
        if not idol:
            # Placeholder profile
            idol = IdolProfile(
                display_name="Grabbed",
                idol_type=IdolType.JAPANESE,
                group_name="Solo"
            )

        downloader = DownloadManager(config, db)
        report = await downloader.download_media(items, idol)
        console.print(f"[bold green]Grab completed![/bold green] New: {report.new_downloaded}, Replaced: {report.replaced_near_duplicate}, Failed: {report.failed}")

@cli.command("list")
@click.option("--by-group", is_flag=True, help="Group list by group names")
@click.pass_context
@coro
async def list_idols(ctx, by_group):
    """List all tracked idols."""
    db_path = ctx.obj["db_path"]
    
    async with Database(db_path) as db:
        idols = await db.list_idols()
        
    if not idols:
        console.print("[yellow]No tracked idols found in database. Add one with 'catchido add'[/yellow]")
        return
        
    table = Table(title="📋 Tracked Idols")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Group", style="magenta")
    table.add_column("Company", style="yellow")
    table.add_column("Status", style="blue")
    
    if by_group:
        # Group by group name
        grouped = {}
        for idol in idols:
            g = idol.group_name or "Solo"
            grouped.setdefault(g, []).append(idol)
            
        for g, members in sorted(grouped.items()):
            for m in members:
                table.add_row(
                    m.display_name,
                    m.idol_type.value.upper(),
                    m.group_name or "-",
                    m.company or "-",
                    m.status.value
                )
    else:
        for idol in idols:
            table.add_row(
                idol.display_name,
                idol.idol_type.value.upper(),
                idol.group_name or "-",
                idol.company or "-",
                idol.status.value
            )
            
    console.print(table)

@cli.command()
@click.argument("name")
@click.pass_context
@coro
async def info(ctx, name):
    """Show details of a tracked idol profile."""
    db_path = ctx.obj["db_path"]
    
    async with Database(db_path) as db:
        idol = await db.get_idol(name)
        if not idol:
            console.print(f"[red]Idol '{name}' not found.[/red]")
            return
            
        keywords = await db.get_keywords_for_idol(name)
        trusted = await db.get_trusted_accounts(name)
        media_count = await db.get_media_count(name)

    # General profile table
    table = Table(show_header=False, title=f"Profile: {idol.display_name}")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Type", idol.idol_type.value.upper())
    if idol.idol_type == IdolType.JAPANESE:
        table.add_row("Kanji Name", idol.kanji_name or "-")
        table.add_row("Generation", idol.generation or "-")
        table.add_row("Team", idol.team or "-")
    else:
        table.add_row("Hangul Name", idol.hangul_name or "-")
        table.add_row("Stage Name", idol.stage_name or "-")
        table.add_row("Real Name", idol.real_name or "-")
        table.add_row("Position(s)", ", ".join(idol.positions) if idol.positions else "-")
        
    table.add_row("Group", idol.group_name or "-")
    table.add_row("Company", idol.company or "-")
    table.add_row("Birthday", idol.birthday or "-")
    table.add_row("Debut Date", idol.debut_date or "-")
    table.add_row("Status", idol.status.value)
    table.add_row("Graduation Date", idol.graduation_date or "-")
    table.add_row("Total Files Downloaded", str(media_count))

    console.print(table)
    
    # Keywords overview
    kw_tags = [k.keyword for k in keywords if k.keyword.startswith("#")]
    kw_terms = [k.keyword for k in keywords if not k.keyword.startswith("#")]
    console.print(f"\n[bold cyan]Search Terms:[/bold cyan] {', '.join(kw_terms[:15])}...")
    console.print(f"[bold cyan]Hashtags:[/bold cyan] {', '.join(kw_tags[:15])}...")
    
    # Trusted accounts — all 5 platforms
    for platform_name in ["twitter", "instagram", "threads", "tiktok", "weibo"]:
        accts = [t.username for t in trusted if t.platform == platform_name]
        if accts:
            console.print(f"[bold cyan]{platform_name.capitalize()} Accounts tracked:[/bold cyan] {', '.join(accts)}")

@cli.command()
@click.pass_context
@coro
async def stats(ctx):
    """Show global download statistics."""
    db_path = ctx.obj["db_path"]
    
    async with Database(db_path) as db:
        stats_data = await db.get_download_stats()
        
    # Format size
    from .utils.helpers import format_filesize
    total_size_str = format_filesize(stats_data["total_size"])
    
    console.print(Panel(
        f"[bold green]📊 Catchido Global Stats[/bold green]\n\n"
        f"Total downloaded files: [cyan]{stats_data['total_count']}[/cyan]\n"
        f"Total disk usage: [cyan]{total_size_str}[/cyan]"
    ))

    table = Table(title="Stats by Platform")
    table.add_column("Platform", style="cyan")
    table.add_column("File Count", style="green")
    table.add_column("Disk Usage", style="yellow")
    
    for platform, details in stats_data["platforms"].items():
        table.add_row(
            platform.capitalize(),
            str(details["count"]),
            format_filesize(details["size"])
        )
    console.print(table)

@cli.command()
@click.option("--dry-run", is_flag=True, help="Scan only, do not delete")
@click.option("--threshold", type=int, default=5, help="Hamming distance threshold")
@click.pass_context
@coro
async def dedup(ctx, dry_run, threshold):
    """Scan disk and remove perceptual duplicate photos."""
    config = ctx.obj["config"]
    db_path = ctx.obj["db_path"]
    
    console.print(f"[bold yellow]Scanning for duplicates...[/bold yellow]")
    
    # We can fetch all records and compute pairwise comparison
    dedup = DedupEngine(threshold=threshold)
    
    async with Database(db_path) as db:
        # Load all media hashes
        async with db._conn.execute("SELECT * FROM media_hashes WHERE phash IS NOT NULL") as cursor:
            rows = await cursor.fetchall()
            
        duplicates = []
        visited = set()
        
        for i, row1 in enumerate(rows):
            path1 = row1["file_path"]
            phash1 = row1["phash"]
            width1 = row1["width"] or 0
            height1 = row1["height"] or 0
            
            if path1 in visited:
                continue
                
            val1 = int(phash1, 16)
            
            # Compare with all subsequent items
            for j in range(i + 1, len(rows)):
                row2 = rows[j]
                path2 = row2["file_path"]
                phash2 = row2["phash"]
                width2 = row2["width"] or 0
                height2 = row2["height"] or 0
                
                if path2 in visited:
                    continue
                    
                val2 = int(phash2, 16)
                dist = bin(val1 ^ val2).count('1')
                
                if dist <= threshold:
                    # Near duplicate!
                    # Choose which one to keep (higher resolution)
                    res1 = width1 * height1
                    res2 = width2 * height2
                    
                    if res1 >= res2:
                        keep_path = path1
                        dup_path = path2
                    else:
                        keep_path = path2
                        dup_path = path1
                        
                    duplicates.append((keep_path, dup_path, dist))
                    visited.add(dup_path)

        if not duplicates:
            console.print("[green]No duplicate images found on disk.[/green]")
            return

        console.print(f"Found [red]{len(duplicates)}[/red] duplicate image pairs:")
        for keep, dup, dist in duplicates:
            console.print(f" - [green]Keep[/green]: {Path(keep).name} vs [red]Delete[/red]: {Path(dup).name} (dist: {dist})")
            
            if not dry_run:
                try:
                    p = Path(dup)
                    if p.exists():
                        p.unlink()
                    # Delete hash entry from database
                    await db._conn.execute("DELETE FROM media_hashes WHERE file_path = ?", (dup,))
                    logger.info("Removed duplicate: {}", dup)
                except Exception as e:
                    logger.error("Failed to delete duplicate {}: {}", dup, e)
                    
        if not dry_run:
            await db._conn.commit()
            console.print(f"[green][OK][/green] Successfully removed [green]{len(duplicates)}[/green] duplicates from disk and database.")
        else:
            console.print(f"[yellow]Dry-run mode: no files were deleted.[/yellow]")

@cli.command()
@click.pass_context
@coro
async def organize(ctx):
    """Reorganize downloaded files into photos and videos subfolders."""
    config = ctx.obj["config"]
    db_path = ctx.obj["db_path"]
    organizer = FileOrganizer(config.general.download_dir)
    console.print("Reorganizing downloaded files...")
    res = organizer.reorganize_existing_files()
    moved_list = res.get("moved", [])
    
    if moved_list:
        async with Database(db_path) as db:
            async with db._conn.cursor() as cursor:
                for old_p, new_p in moved_list:
                    await cursor.execute("UPDATE media_hashes SET file_path = ? WHERE file_path = ?", (new_p, old_p))
            await db._conn.commit()
            
    console.print(f"[bold green][OK][/bold green] Reorganization complete! Migrated [cyan]{len(moved_list)}[/cyan] files, cleaned up [cyan]{res['cleaned_dirs']}[/cyan] empty folders.")

@cli.command()
@click.pass_context
def tui(ctx):
    """Launch Catchido interactive TUI (Terminal User Interface)."""
    try:
        from .tui.app import CatchidoApp
    except ImportError:
        console.print("[red]TUI dependencies not found. Install with: pip install 'catchido[tui]'[/red]")
        console.print("[yellow]Required: textual>=0.80[/yellow]")
        return
    
    config = ctx.obj["config"]
    db_path = ctx.obj["db_path"]
    
    # Auto-initialize database schema before starting the TUI app
    async def init_db():
        from .db import Database
        async with Database(db_path) as db:
            await db.initialize()
            
    asyncio.run(init_db())
    
    app = CatchidoApp(config=config, db_path=db_path)
    app.run()

@cli.command()
@click.option("--host", default="localhost", help="Host interface to bind server to")
@click.option("--port", default=8000, help="Port to run web server on")
@click.pass_context
def web(ctx, host, port):
    """Launch Catchido interactive Web GUI dashboard."""
    console.print(f"[bold green]Starting Catchido Web GUI...[/bold green]")
    console.print(f"[green][OK][/green] Open your browser at: [bold cyan]http://{host}:{port}[/bold cyan]")
    
    from .web.server import run_server
    run_server(host=host, port=port)

if __name__ == "__main__":
    cli()
