import re
import json
import asyncio
import random
from typing import List, Optional, Dict, Any
from loguru import logger
import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper
from ..db.models import MediaItem, MediaType

class ThreadsScraper(BaseScraper):
    def __init__(self, session_cookie: str, config):
        super().__init__(config, request_delay=config.threads.request_delay)
        self.session_cookie = session_cookie

    def get_hd_url(self, url: str) -> str:
        """
        Threads uses Instagram CDN (scontent-*.cdninstagram.com).
        We strip formatting query parameters (like stp) if present, to get the original/highest resolution.
        """
        if "stp=" in url:
            url = re.sub(r'&stp=[^&]+', '', url)
        return url

    async def _create_session(self) -> httpx.AsyncClient:
        client = await super()._create_session()
        client.headers.update({
            "Referer": "https://www.threads.net/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-IG-App-ID": "2382947238294"
        })
        if self.session_cookie:
            client.headers["Cookie"] = self.session_cookie
            logger.debug("Threads session cookie loaded")
        return client

    async def fetch_media(
        self, 
        query_or_username: str, 
        since_id: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[MediaItem]:
        """Fetch media items from a Threads user profile."""
        username = query_or_username.lstrip("@")
        if not self.client:
            await self._create_session()

        url = f"https://www.threads.net/@{username}"
        logger.info("Fetching Threads profile for user: {}", username)

        try:
            await self._throttle()
            resp = await self.client.get(url)
            if resp.status_code != 200:
                logger.error("Failed to fetch Threads profile {}: {}", username, resp.status_code)
                return []

            html = resp.text
            media_items = self._parse_threads_html(html, username)
            
            filtered_items = []
            for item in media_items:
                if since_id and item.post_id == since_id:
                    logger.info("Reached Threads checkpoint since_id: {}. Stopping.", since_id)
                    break
                filtered_items.append(item)
                if limit and len(filtered_items) >= limit:
                    break

            logger.info("Retrieved {} media items for @{} from Threads profile.", len(filtered_items), username)
            return filtered_items
        except Exception as e:
            logger.exception("Error during Threads scraping for @{}: {}", username, e)
            return []

    async def fetch_media_from_url(self, url: str) -> List[MediaItem]:
        """Fetch media items directly from a specific Threads post URL."""
        if not self.client:
            await self._create_session()

        logger.info("Fetching Threads post from URL: {}", url)
        try:
            await self._throttle()
            resp = await self.client.get(url)
            if resp.status_code != 200:
                logger.error("Failed to fetch Threads post URL (Status {}).", resp.status_code)
                return []

            author = "unknown"
            match = re.search(r'threads\.net/@([^/]+)', url)
            if match:
                author = match.group(1)

            html = resp.text
            return self._parse_threads_html(html, author)
        except Exception as e:
            logger.exception("Error fetching Threads post URL {}: {}", url, e)
            return []

    def _parse_threads_html(self, html: str, author: str) -> List[MediaItem]:
        """Parse raw Threads HTML page and extract media items from JSON state scripts."""
        media_items = []
        soup = BeautifulSoup(html, "lxml")

        script_tags = soup.find_all("script", type="application/json")
        for tag in script_tags:
            content = tag.string
            if not content:
                continue
            
            if "scontent" in content and ("image_versions" in content or "candidate" in content or "code" in content):
                try:
                    data = json.loads(content)
                    items = self._extract_media_from_json(data, author)
                    media_items.extend(items)
                except Exception:
                    pass

        if not media_items:
            logger.debug("Falling back to regex parsing for Threads media links")
            cdn_pattern = r'https://scontent[^"\']+\.cdninstagram\.com/[^"\']+\.(?:jpg|jpeg|png|webp|mp4)'
            urls = re.findall(cdn_pattern, html)
            unique_urls = list(set(urls))
            
            for idx, cdn_url in enumerate(unique_urls):
                clean_url = cdn_url.replace("\\u0026", "&").replace("&amp;", "&")
                
                ext = clean_url.split("?")[0].split(".")[-1].lower()
                media_type = MediaType.VIDEO if ext in ["mp4", "webm"] else MediaType.IMAGE
                
                if media_type == MediaType.VIDEO and not self.config.general.download_videos:
                    continue
                if media_type == MediaType.IMAGE and not self.config.general.download_photos:
                    continue

                import hashlib
                post_id = hashlib.md5(clean_url.encode('utf-8')).hexdigest()[:16]

                media_items.append(MediaItem(
                    url=self.get_hd_url(clean_url),
                    platform="threads",
                    post_id=post_id,
                    author=author,
                    media_type=media_type,
                    original_url=clean_url,
                    text=""
                ))

        unique_results = {}
        for item in media_items:
            unique_results[item.url] = item
        return list(unique_results.values())

    def _extract_media_from_json(self, data: Any, author: str) -> List[MediaItem]:
        """Recursively scan JSON tree for Threads post nodes and map to MediaItem."""
        items = []

        if isinstance(data, dict):
            is_post = "code" in data and ("image_versions" in data or "carousel_media" in data or "video_versions" in data)
            if is_post:
                post_id = data.get("code") or data.get("id") or str(random.randint(100000, 999999))
                caption_text = data.get("caption", {}).get("text", "")
                hashtags = [tag.strip("#") for tag in re.findall(r'#\w+', caption_text)]
                
                created_at_ts = data.get("taken_at")
                created_at = None
                if created_at_ts:
                    from datetime import datetime
                    created_at = datetime.utcfromtimestamp(created_at_ts).isoformat()

                carousel = data.get("carousel_media", [])
                if carousel:
                    for idx, child in enumerate(carousel):
                        items.extend(self._parse_single_item(child, f"{post_id}_{idx}", author, created_at, caption_text, hashtags))
                else:
                    items.extend(self._parse_single_item(data, post_id, author, created_at, caption_text, hashtags))
            else:
                for val in data.values():
                    items.extend(self._extract_media_from_json(val, author))
        elif isinstance(data, list):
            for val in data:
                items.extend(self._extract_media_from_json(val, author))

        return items

    def _parse_single_item(
        self, 
        item: Dict[str, Any], 
        post_id: str, 
        author: str, 
        created_at: Optional[str],
        text: str, 
        hashtags: List[str]
    ) -> List[MediaItem]:
        res = []
        
        video_versions = item.get("video_versions", [])
        if video_versions and self.config.general.download_videos:
            video_versions.sort(key=lambda x: x.get("width", 0), reverse=True)
            url = video_versions[0].get("url")
            width = video_versions[0].get("width")
            height = video_versions[0].get("height")
            if url:
                res.append(MediaItem(
                    url=url,
                    platform="threads",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.VIDEO,
                    width=width,
                    height=height,
                    original_url=url,
                    created_at=created_at,
                    text=text,
                    hashtags=hashtags
                ))
        
        image_versions = item.get("image_versions", {}).get("candidates", []) or item.get("candidates", [])
        if image_versions and self.config.general.download_photos:
            image_versions.sort(key=lambda x: x.get("width", 0), reverse=True)
            url = image_versions[0].get("url")
            width = image_versions[0].get("width")
            height = image_versions[0].get("height")
            if url:
                res.append(MediaItem(
                    url=self.get_hd_url(url),
                    platform="threads",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.IMAGE,
                    width=width,
                    height=height,
                    original_url=url,
                    created_at=created_at,
                    text=text,
                    hashtags=hashtags
                ))
        return res
