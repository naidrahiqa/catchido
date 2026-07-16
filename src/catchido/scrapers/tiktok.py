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

class TikTokScraper(BaseScraper):
    def __init__(self, session_cookie: str, config):
        super().__init__(config, request_delay=config.tiktok.request_delay)
        self.session_cookie = session_cookie

    def get_hd_url(self, url: str) -> str:
        """
        TikTok photo URLs are usually HD.
        We can strip query parameters or modify image size parameters if needed.
        """
        return url

    async def _create_session(self) -> httpx.AsyncClient:
        client = await super()._create_session()
        client.headers.update({
            "Referer": "https://www.tiktok.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none"
        })
        if self.session_cookie:
            # TikTok session cookie is usually called 'sessionid' or similar,
            # we will set the Cookie header directly.
            client.headers["Cookie"] = f"sessionid={self.session_cookie}"
            logger.debug("TikTok session cookie loaded")
        return client

    async def fetch_media(
        self, 
        query_or_username: str, 
        since_id: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[MediaItem]:
        """Fetch media items (photo slides) from a TikTok user profile."""
        username = query_or_username.lstrip("@")
        if not self.client:
            await self._create_session()

        url = f"https://www.tiktok.com/@{username}"
        logger.info("Fetching TikTok profile for @{}", username)

        try:
            await self._throttle()
            resp = await self.client.get(url)
            if resp.status_code != 200:
                logger.error("TikTok profile fetch failed for @{} (Status {}).", username, resp.status_code)
                return []

            html = resp.text
            media_items = self._parse_tiktok_html(html, username)
            
            filtered_items = []
            for item in media_items:
                if since_id and item.post_id == since_id:
                    logger.info("Reached TikTok checkpoint since_id: {}. Stopping.", since_id)
                    break
                filtered_items.append(item)
                if limit and len(filtered_items) >= limit:
                    break

            logger.info("Retrieved {} media items for @{} from TikTok profile.", len(filtered_items), username)
            return filtered_items
        except Exception as e:
            logger.exception("Error during TikTok scraping for @{}: {}", username, e)
            return []

    async def fetch_media_from_url(self, url: str) -> List[MediaItem]:
        """Fetch media items directly from a specific TikTok post URL."""
        if not self.client:
            await self._create_session()

        logger.info("Fetching TikTok post from URL: {}", url)
        try:
            await self._throttle()
            # Handle shortened links (e.g. vm.tiktok.com / vt.tiktok.com)
            resp = await self.client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                logger.error("Failed to fetch TikTok post URL (Status {}).", resp.status_code)
                return []

            # Extract post owner/author from redirected URL or HTML
            author = "unknown"
            match = re.search(r'tiktok\.com/@([^/]+)', str(resp.url))
            if match:
                author = match.group(1)

            html = resp.text
            return self._parse_tiktok_html(html, author)
        except Exception as e:
            logger.exception("Error fetching TikTok post URL {}: {}", url, e)
            return []

    def _parse_tiktok_html(self, html: str, author: str) -> List[MediaItem]:
        """Parse raw TikTok HTML and extract photo slides from state JSON script tags."""
        media_items = []
        soup = BeautifulSoup(html, "lxml")

        # Find rehydration or state script tag
        script_tags = [
            soup.find("script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__"),
            soup.find("script", id="SIGI_STATE"),
            soup.find("script", id="sigi-state")
        ]
        
        # Also look in all script tags containing typical TikTok JSON
        for tag in soup.find_all("script"):
            if tag.string and ("__UNIVERSAL_DATA_FOR_REHYDRATION__" in tag.string or "SIGI_STATE" in tag.string or "itemStruct" in tag.string):
                script_tags.append(tag)

        for tag in script_tags:
            if not tag or not tag.string:
                continue
            
            content = tag.string.strip()
            # Clean up JS assignment if needed (e.g. window.SIGI_STATE = ...)
            if "=" in content and not content.startswith("{"):
                match = re.search(r'=\s*(\{.*?\});?$', content, re.DOTALL)
                if match:
                    content = match.group(1)

            try:
                data = json.loads(content)
                items = self._extract_media_from_json(data, author)
                media_items.extend(items)
            except Exception:
                pass

        # Fallback: Regex parse TikTok photo CDN urls if JSON failed
        if not media_items and self.config.general.download_photos:
            logger.debug("Falling back to regex parsing for TikTok photo CDN URLs")
            # TikTok CDNs use tiktokcdn.com / byteoversea.com / ibyteimg.com / tiktokcdn-us.com
            cdn_pattern = r'https://[a-zA-Z0-9.-]+\.(?:tiktokcdn|byteoversea|ibyteimg|tiktokcdn-us)\.com/[^"\']+\.(?:jpg|jpeg|png|webp)'
            urls = re.findall(cdn_pattern, html)
            unique_urls = list(set(urls))
            
            for idx, cdn_url in enumerate(unique_urls):
                clean_url = cdn_url.replace("\\u0026", "&").replace("&amp;", "&")
                import hashlib
                post_id = hashlib.md5(clean_url.encode('utf-8')).hexdigest()[:16]

                media_items.append(MediaItem(
                    url=self.get_hd_url(clean_url),
                    platform="tiktok",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.IMAGE,
                    original_url=clean_url,
                    text=""
                ))

        # De-duplicate items list
        unique_results = {}
        for item in media_items:
            unique_results[item.url] = item
        return list(unique_results.values())

    def _extract_media_from_json(self, data: Any, author: str) -> List[MediaItem]:
        """Recursively scan JSON tree for TikTok post structs and map to MediaItem."""
        items = []

        if isinstance(data, dict):
            # Check for itemStruct or individual item representation
            is_post = "id" in data and ("imagePost" in data or "video" in data or "desc" in data)
            if is_post:
                post_id = data.get("id") or str(random.randint(100000, 999999))
                caption_text = data.get("desc") or data.get("caption") or ""
                hashtags = [tag.strip("#") for tag in re.findall(r'#\w+', caption_text)]
                
                created_at_ts = data.get("createTime") or data.get("addedTime")
                created_at = None
                if created_at_ts:
                    from datetime import datetime
                    created_at = datetime.utcfromtimestamp(int(created_at_ts)).isoformat()

                # Process photo slideshow (imagePost)
                image_post_info = data.get("imagePost") or data.get("image_post_info")
                if image_post_info and self.config.general.download_photos:
                    images = image_post_info.get("images", [])
                    for idx, img in enumerate(images):
                        # Extract URL candidates
                        display_url = None
                        # structure can be img['display_image']['url_list'][0] or similar
                        url_list = img.get("display_image", {}).get("url_list", []) or img.get("url_list", []) or []
                        if url_list:
                            display_url = url_list[0]
                        else:
                            display_url = img.get("url")
                            
                        width = img.get("width") or img.get("display_image", {}).get("width")
                        height = img.get("height") or img.get("display_image", {}).get("height")
                        
                        if display_url:
                            items.append(MediaItem(
                                url=self.get_hd_url(display_url),
                                platform="tiktok",
                                post_id=f"{post_id}_{idx}",
                                author=author,
                                media_type=MediaType.IMAGE,
                                width=width,
                                height=height,
                                original_url=display_url,
                                created_at=created_at,
                                text=caption_text,
                                hashtags=hashtags
                            ))
                
                # Check for video if download_videos is enabled
                elif "video" in data and self.config.general.download_videos:
                    video_struct = data.get("video", {})
                    # Get downloadAddr or playAddr
                    url = video_struct.get("downloadAddr") or video_struct.get("playAddr")
                    width = video_struct.get("width")
                    height = video_struct.get("height")
                    if url:
                        items.append(MediaItem(
                            url=url,
                            platform="tiktok",
                            post_id=post_id,
                            author=author,
                            media_type=MediaType.VIDEO,
                            width=width,
                            height=height,
                            original_url=url,
                            created_at=created_at,
                            text=caption_text,
                            hashtags=hashtags
                        ))
            else:
                for val in data.values():
                    items.extend(self._extract_media_from_json(val, author))
        elif isinstance(data, list):
            for val in data:
                items.extend(self._extract_media_from_json(val, author))

        return items
