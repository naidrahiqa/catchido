import asyncio
from typing import Optional
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Label, Button, Select, RichLog, ProgressBar
from loguru import logger

from ...db import Database
from ...config import get_config
from ...scrapers.twitter import TwitterScraper
from ...scrapers.weibo import WeiboScraper
from ...scrapers.instagram import InstagramScraper
from ...scrapers.threads import ThreadsScraper
from ...scrapers.tiktok import TikTokScraper
from ...core.downloader import DownloadManager
from ...keywords.scorer import RelevanceScorer, PostData
from ...keywords.expander import KeywordExpander
from ...db.models import IdolKeywordEntry, DownloadCheckpoint, MediaItem

class DownloadView(Container):
    def __init__(self, db_path, config, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.config = config
        self.download_task = None
        
        self.idol_select = Select([], prompt="Select an idol or ALL", id="select-idol")
        self.start_btn = Button("🚀 Start Scrape", id="btn-start-download", classes="sidebar-btn primary")
        self.stop_btn = Button("🛑 Stop", id="btn-stop-download", classes="sidebar-btn", disabled=True)
        self.log_widget = RichLog(highlight=True, markup=True, max_lines=500, id="download-log")
        self.progress_bar = ProgressBar(id="download-progress")

    def compose(self) -> ComposeResult:
        yield Label("[bold #ff6bcb]Scraper Control Panel[/bold #ff6bcb]", classes="section-title")
        yield Horizontal(
            self.idol_select,
            self.start_btn,
            self.stop_btn,
            classes="download-control-row"
        )
        yield self.progress_bar
        yield Container(
            self.log_widget,
            classes="log-panel"
        )

    async def on_mount(self) -> None:
        await self.refresh_idols_list()

    async def refresh_idols_list(self) -> None:
        try:
            async with Database(self.db_path) as db:
                idols = await db.list_idols()
            options = [(idol.display_name, idol.display_name) for idol in idols]
            options.insert(0, ("All Tracked Idols", "ALL"))
            self.idol_select.set_options(options)
        except Exception as e:
            self.log_widget.write(f"[red]Error loading idols list: {e}[/red]")

    def select_idol(self, name: str) -> None:
        self.idol_select.value = name

    def log_message(self, message: str) -> None:
        self.log_widget.write(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start-download":
            target = self.idol_select.value
            if target == Select.BLANK:
                self.log_widget.write("[yellow]Please select a target to download first.[/yellow]")
                return
            self.start_btn.disabled = True
            self.stop_btn.disabled = False
            self.log_widget.clear()
            self.log_widget.write(f"[green]Starting download job for: {target}...[/green]")
            # Start background async job
            self.run_worker(self.download_job(target), name="download_job", group="downloads")
        elif event.button.id == "btn-stop-download":
            self.log_widget.write("[yellow]Stopping current download job...[/yellow]")
            self.workers.cancel_group("downloads")
            self.start_btn.disabled = False
            self.stop_btn.disabled = True

    async def download_job(self, target: str) -> None:
        # Re-route loguru logging to our TUI log widget
        log_widget = self.log_widget
        class TUILogHandler:
            def write(self, message):
                # Clean up formatting for rich markup
                cleaned = message.strip().replace("[", "\\[").replace("]", "\\]")
                # Restore color markup if they were added via rich
                log_widget.write(cleaned)
        
        # In a real app we'd add/remove handlers, but here we will write direct status updates
        try:
            targets = []
            async with Database(self.db_path) as db:
                if target == "ALL":
                    targets = await db.list_idols()
                else:
                    idol = await db.get_idol(target)
                    if idol:
                        targets = [idol]

            if not targets:
                log_widget.write("[yellow]No idols to process.[/yellow]")
                return

            # Initialize scrapers
            log_widget.write("[blue]Initializing scrapers...[/blue]")
            tw_scraper = TwitterScraper(self.config.twitter.bearer_token, self.config)
            wb_scraper = WeiboScraper(self.config.weibo.cookie, self.config)
            ig_scraper = InstagramScraper(self.config.instagram.session_cookie, self.config)
            th_scraper = ThreadsScraper(self.config.threads.session_cookie, self.config)
            tk_scraper = TikTokScraper(self.config.tiktok.session_cookie, self.config)
            downloader = DownloadManager(self.config, db)
            
            scorer = RelevanceScorer(self.config.search.min_relevance_score)
            expander = KeywordExpander()

            self.progress_bar.update(total=len(targets), progress=0)
            
            for idx, idol in enumerate(targets):
                log_widget.write(f"\n[bold #ff6bcb]=====================[/bold #ff6bcb]")
                log_widget.write(f"[bold #ff6bcb]Processing: {idol.display_name} ({idol.idol_type.value.upper()})[/bold #ff6bcb]")
                log_widget.write(f"[bold #ff6bcb]=====================[/bold #ff6bcb]")
                
                trusted = await db.get_trusted_accounts(idol.display_name)
                trusted_usernames = [t.username for t in trusted]
                keywords = await db.get_keywords_for_idol(idol.display_name)
                
                exclude_terms = ["cosplay", "fanart", "AI생성"]
                search_terms = [k.keyword for k in keywords if not k.keyword.startswith("#")]
                hashtags = [k.keyword for k in keywords if k.keyword.startswith("#")]
                
                tw_query = expander.build_twitter_query(search_terms, exclude_terms)
                wb_queries = expander.build_weibo_queries(
                    kanji_name=idol.kanji_name,
                    hangul_name=idol.hangul_name,
                    stage_name=idol.stage_name,
                    group=idol.group_name,
                    hashtags=hashtags
                )

                media_items_to_download = []

                # Scrape X/Twitter
                if self.config.twitter.bearer_token:
                    log_widget.write(f"[{idol.display_name}] Scraping Twitter sources...")
                    tw_sources = [t.username for t in trusted if t.platform == "twitter"]
                    for tw_src in tw_sources:
                        chk = await db.get_checkpoint(idol.display_name, "twitter", tw_src)
                        items = await tw_scraper.fetch_media(tw_src, since_id=chk, limit=20)
                        media_items_to_download.extend(items)
                        if items:
                            try:
                                latest_id = max(int(item.post_id) for item in items if item.post_id.isdigit())
                                await db.update_checkpoint(DownloadCheckpoint(
                                    idol_name=idol.display_name, platform="twitter",
                                    source_username=tw_src, last_id=str(latest_id)
                                ))
                            except Exception:
                                await db.update_checkpoint(DownloadCheckpoint(
                                    idol_name=idol.display_name, platform="twitter",
                                    source_username=tw_src, last_id=items[0].post_id
                                ))
                    
                    if self.config.search.auto_generate_keywords:
                        search_items = await tw_scraper.fetch_media(tw_query, limit=20)
                        for item in search_items:
                            post = PostData(text=item.text, hashtags=item.hashtags, author=item.author, platform="twitter")
                            if scorer.calculate_relevance(post, idol, trusted_usernames) >= self.config.search.min_relevance_score:
                                media_items_to_download.append(item)

                # Scrape Weibo
                log_widget.write(f"[{idol.display_name}] Scraping Weibo sources...")
                wb_sources = [t.username for t in trusted if t.platform == "weibo"]
                for wb_src in wb_sources:
                    chk = await db.get_checkpoint(idol.display_name, "weibo", wb_src)
                    items = await wb_scraper.fetch_media(wb_src, since_id=chk, limit=20)
                    media_items_to_download.extend(items)
                    if items:
                        try:
                            latest_id = max(int(item.post_id) for item in items if item.post_id.isdigit())
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="weibo",
                                source_username=wb_src, last_id=str(latest_id)
                            ))
                        except Exception:
                            pass

                for wb_q in wb_queries:
                    search_items = await wb_scraper.fetch_media(wb_q, limit=20)
                    for item in search_items:
                        post = PostData(text=item.text, hashtags=item.hashtags, author=item.author, platform="weibo")
                        if scorer.calculate_relevance(post, idol, trusted_usernames) >= self.config.search.min_relevance_score:
                            media_items_to_download.append(item)

                # Scrape Instagram
                log_widget.write(f"[{idol.display_name}] Scraping Instagram sources...")
                ig_sources = [t.username for t in trusted if t.platform == "instagram"]
                for ig_src in ig_sources:
                    chk = await db.get_checkpoint(idol.display_name, "instagram", ig_src)
                    items = await ig_scraper.fetch_media(ig_src, since_id=chk, limit=20)
                    media_items_to_download.extend(items)
                    if items:
                        try:
                            latest_id = max(int(item.post_id) for item in items if item.post_id.isdigit())
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="instagram",
                                source_username=ig_src, last_id=str(latest_id)
                            ))
                        except:
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="instagram",
                                source_username=ig_src, last_id=items[0].post_id
                            ))

                # Scrape Threads
                log_widget.write(f"[{idol.display_name}] Scraping Threads sources...")
                th_sources = [t.username for t in trusted if t.platform == "threads"]
                for th_src in th_sources:
                    chk = await db.get_checkpoint(idol.display_name, "threads", th_src)
                    items = await th_scraper.fetch_media(th_src, since_id=chk, limit=20)
                    media_items_to_download.extend(items)
                    if items:
                        try:
                            latest_id = max(int(item.post_id) for item in items if item.post_id.isdigit())
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="threads",
                                source_username=th_src, last_id=str(latest_id)
                            ))
                        except Exception:
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="threads",
                                source_username=th_src, last_id=items[0].post_id
                            ))

                # Scrape TikTok
                log_widget.write(f"[{idol.display_name}] Scraping TikTok sources...")
                tk_sources = [t.username for t in trusted if t.platform == "tiktok"]
                for tk_src in tk_sources:
                    chk = await db.get_checkpoint(idol.display_name, "tiktok", tk_src)
                    items = await tk_scraper.fetch_media(tk_src, since_id=chk, limit=20)
                    media_items_to_download.extend(items)
                    if items:
                        try:
                            latest_id = max(int(item.post_id) for item in items if item.post_id.isdigit())
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="tiktok",
                                source_username=tk_src, last_id=str(latest_id)
                            ))
                        except Exception:
                            await db.update_checkpoint(DownloadCheckpoint(
                                idol_name=idol.display_name, platform="tiktok",
                                source_username=tk_src, last_id=items[0].post_id
                            ))

                # Filter duplicates out of memory
                unique_items = {}
                for item in media_items_to_download:
                    unique_items[item.url] = item
                
                final_download_list = list(unique_items.values())
                log_widget.write(f"[{idol.display_name}] Resolved {len(final_download_list)} unique candidates to download.")

                if final_download_list:
                    log_widget.write(f"[{idol.display_name}] Initiating download and dedup pipeline...")
                    # Run downloader
                    report = await downloader.download_media(final_download_list, idol)
                    log_widget.write(f"[green]Finished {idol.display_name} download batch! New: {report.new_downloaded}, Replaced: {report.replaced_near_duplicate}, Skipped: {report.skipped_duplicate}, Failed: {report.failed}[/green]")
                else:
                    log_widget.write(f"[yellow]No new media found for {idol.display_name}.[/yellow]")

                self.progress_bar.advance()

            # Close all scraper sessions
            await tw_scraper.close()
            await wb_scraper.close()
            await ig_scraper.close()
            await th_scraper.close()
            await tk_scraper.close()
            
            log_widget.write("\n[bold green]⭐⭐ Scrape Session Completed Successfully! ⭐⭐[/bold green]")
        except asyncio.CancelledError:
            log_widget.write("\n[red]❌ Download job was cancelled by user.[/red]")
        except Exception as e:
            log_widget.write(f"\n[red]❌ Critical error in download job: {e}[/red]")
        finally:
            self.start_btn.disabled = False
            self.stop_btn.disabled = True
