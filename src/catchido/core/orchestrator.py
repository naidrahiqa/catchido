from typing import List, Optional
from loguru import logger

from ..db import Database
from ..db.models import (
    IdolProfile, MediaItem, DownloadCheckpoint
)
from ..scrapers.twitter import TwitterScraper
from ..scrapers.weibo import WeiboScraper
from ..scrapers.instagram import InstagramScraper
from ..scrapers.threads import ThreadsScraper
from ..scrapers.tiktok import TikTokScraper
from .downloader import DownloadManager, DownloadReport
from ..keywords.expander import KeywordExpander
from ..keywords.scorer import RelevanceScorer, PostData


async def run_scrape_and_download(
    db: Database,
    config,
    targets: List[IdolProfile],
    depth: str = "recent",
) -> None:
    """
    Shared download orchestration used by both CLI and web server.

    Args:
        db: An open Database instance (caller manages lifecycle).
        config: The loaded AppConfig.
        targets: Idol profiles to scrape for.
        depth: "recent" for quick incremental, "full" for deep scrape.
    """
    tw_scraper = TwitterScraper(config.twitter.bearer_token, config)
    wb_scraper = WeiboScraper(config.weibo.cookie, config)
    ig_scraper = InstagramScraper(config.instagram.session_cookie, config)
    th_scraper = ThreadsScraper(config.threads.session_cookie, config)
    tk_scraper = TikTokScraper(config.tiktok.session_cookie, config)
    downloader = DownloadManager(config, db)

    scorer = RelevanceScorer(config.search.min_relevance_score)
    expander = KeywordExpander()

    try:
        for idol in targets:
            logger.info("=== Starting Scrape for {} ===", idol.display_name)

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

            media_items_to_download: List[MediaItem] = []

            # Twitter
            if config.twitter.bearer_token:
                tw_sources = [t.username for t in trusted if t.platform == "twitter"]
                for src in tw_sources:
                    src_query = src if src.startswith("@") else f"@{src}"
                    chk = await db.get_checkpoint(idol.display_name, "twitter", src) if depth == "recent" else None
                    limit = 20 if depth == "recent" else 200
                    items = await tw_scraper.fetch_media(src_query, since_id=chk, limit=limit)
                    media_items_to_download.extend(items)
                    if items:
                        await _update_checkpoint(db, idol.display_name, "twitter", src, items)

                if tw_query:
                    logger.info("Twitter keyword search: {}", tw_query)
                    kw_items = await tw_scraper.fetch_media(tw_query, since_id=None, limit=50)
                    media_items_to_download.extend(kw_items)
                    logger.info("Twitter keyword search returned {} items", len(kw_items))

            # Weibo
            wb_sources = [t.username for t in trusted if t.platform == "weibo"]
            for src in wb_sources:
                chk = await db.get_checkpoint(idol.display_name, "weibo", src) if depth == "recent" else None
                limit = 20 if depth == "recent" else 200
                items = await wb_scraper.fetch_media(src, since_id=chk, limit=limit)
                media_items_to_download.extend(items)
                if items:
                    await _update_checkpoint(db, idol.display_name, "weibo", src, items)

            if wb_queries:
                for wq in wb_queries:
                    logger.info("Weibo keyword search: {}", wq)
                    kw_items = await wb_scraper.fetch_media(wq, since_id=None, limit=30)
                    media_items_to_download.extend(kw_items)
                    logger.info("Weibo keyword search '{}' returned {} items", wq, len(kw_items))

            # Instagram
            ig_sources = [t.username for t in trusted if t.platform == "instagram"]
            for src in ig_sources:
                chk = await db.get_checkpoint(idol.display_name, "instagram", src) if depth == "recent" else None
                limit = 20 if depth == "recent" else None
                items = await ig_scraper.fetch_media(src, since_id=chk, limit=limit)
                media_items_to_download.extend(items)
                if items:
                    await _update_checkpoint(db, idol.display_name, "instagram", src, items)

            # Threads
            th_sources = [t.username for t in trusted if t.platform == "threads"]
            for src in th_sources:
                chk = await db.get_checkpoint(idol.display_name, "threads", src) if depth == "recent" else None
                limit = 20 if depth == "recent" else 200
                items = await th_scraper.fetch_media(src, since_id=chk, limit=limit)
                media_items_to_download.extend(items)
                if items:
                    await _update_checkpoint(db, idol.display_name, "threads", src, items)

            # TikTok
            tk_sources = [t.username for t in trusted if t.platform == "tiktok"]
            for src in tk_sources:
                chk = await db.get_checkpoint(idol.display_name, "tiktok", src) if depth == "recent" else None
                limit = 20 if depth == "recent" else 200
                items = await tk_scraper.fetch_media(src, since_id=chk, limit=limit)
                media_items_to_download.extend(items)
                if items:
                    await _update_checkpoint(db, idol.display_name, "tiktok", src, items)

            # Deduplicate by URL and download
            unique_items: dict[str, MediaItem] = {}
            for item in media_items_to_download:
                unique_items[item.url] = item

            final_download = list(unique_items.values())
            logger.info("Found {} unique media items for {}", len(final_download), idol.display_name)

            if final_download:
                report = await downloader.download_media(final_download, idol)
                logger.info(
                    "Finished: New: {}, Replaced: {}, Skipped: {}, Failed: {}",
                    report.new_downloaded, report.replaced_near_duplicate,
                    report.skipped_duplicate, report.failed
                )
    finally:
        await tw_scraper.close()
        await wb_scraper.close()
        await ig_scraper.close()
        await th_scraper.close()
        await tk_scraper.close()

        logger.info("=== Scrape Session Finished ===")


async def _update_checkpoint(
    db: Database,
    idol_name: str,
    platform: str,
    source_username: str,
    items: List[MediaItem],
) -> None:
    """Update the download checkpoint for a platform source."""
    try:
        numeric_ids = [int(item.post_id) for item in items if item.post_id.isdigit()]
        if numeric_ids:
            latest_id = max(numeric_ids)
            last_id = str(latest_id)
        else:
            last_id = items[0].post_id
        await db.update_checkpoint(DownloadCheckpoint(
            idol_name=idol_name,
            platform=platform,
            source_username=source_username,
            last_id=last_id,
        ))
    except Exception as e:
        logger.error("Failed to update checkpoint for {}/{}: {}", platform, source_username, e)
