import re
import json
import asyncio
import random
from typing import List, Optional, Dict, Any
from loguru import logger
import httpx

from .base import BaseScraper
from ..db.models import MediaItem, MediaType

MAX_PAGE_RETRIES = 3

class InstagramScraper(BaseScraper):
    def __init__(self, session_cookie: str, config):
        super().__init__(config, request_delay=config.instagram.request_delay)
        self.session_cookie = session_cookie

    def get_hd_url(self, url: str) -> str:
        """Instagram CDN URLs are already high resolution."""
        return url

    async def _create_session(self) -> httpx.AsyncClient:
        client = await super()._create_session()
        client.headers.update({
            "Referer": "https://www.instagram.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        })
        if self.session_cookie:
            client.headers["Cookie"] = f"sessionid={self.session_cookie}"
            logger.debug("Instagram session ID cookie loaded")
        return client

    async def _fetch_with_retry(self, url: str, headers: dict) -> Optional[httpx.Response]:
        """GET with exponential backoff retry."""
        for attempt in range(MAX_PAGE_RETRIES):
            try:
                resp = await self.client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp
                logger.warning(
                    "Instagram request attempt {}/{} failed (HTTP {})",
                    attempt + 1, MAX_PAGE_RETRIES, resp.status_code,
                )
            except Exception as e:
                logger.warning(
                    "Instagram request attempt {}/{} error: {}",
                    attempt + 1, MAX_PAGE_RETRIES, e,
                )
            if attempt < MAX_PAGE_RETRIES - 1:
                backoff = (2 ** attempt) * 3 + random.uniform(1, 3)
                await asyncio.sleep(backoff)
        return None

    async def fetch_media(
        self, 
        query_or_username: str, 
        since_id: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[MediaItem]:
        """Fetch media posts from an Instagram user profile with pagination and retry."""
        username = query_or_username.lstrip("@")
        
        if not self.session_cookie:
            logger.warning("Instagram Session Cookie is not configured. Profile scraping might be limited or blocked.")
            
        if not self.client:
            await self._create_session()
            
        headers = {
            "User-Agent": self._get_random_ua(),
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/{username}/"
        }
        
        # Method 1: REST user feed API with retry + pagination
        feed_url = f"https://www.instagram.com/api/v1/feed/user/{username}/username/"
        logger.info("Attempting REST feed fetch for Instagram user: {}", username)
        
        await self._throttle()
        resp = await self._fetch_with_retry(feed_url, headers)
        
        if resp is None:
            logger.warning("REST feed unavailable for {}, falling back to GraphQL.", username)
            return await self._fetch_graphql(username, since_id, limit)
        
        feed_data = resp.json()
        items = feed_data.get("items", [])
        more_available = feed_data.get("more_available", False)
        next_max_id = feed_data.get("next_max_id")
        
        media_items = []
        items_needed = limit if limit is not None else 100000
        
        hit_since = False
        for item in items:
            post_id = item.get("id")
            if since_id and post_id == since_id:
                logger.info("Reached Instagram checkpoint: {}. Stopping.", since_id)
                hit_since = True
                break
            media_items.extend(self._parse_item_api(item))
            if len(media_items) >= items_needed:
                break
        
        # Paginate with retry
        while more_available and next_max_id and len(media_items) < items_needed and not hit_since:
            delay = self.config.instagram.request_delay + random.uniform(0.5, 1.5)
            await asyncio.sleep(delay)
            
            next_url = f"https://www.instagram.com/api/v1/feed/user/{username}/username/?max_id={next_max_id}"
            logger.debug("Fetching next page for {} using max_id: {}", username, next_max_id)
            
            page_resp = await self._fetch_with_retry(next_url, headers)
            if page_resp is None:
                logger.error("Failed to fetch page after retries, stopping pagination for {}", username)
                break
            
            feed_data = page_resp.json()
            items = feed_data.get("items", [])
            if not items:
                break
            
            for item in items:
                post_id = item.get("id")
                if since_id and post_id == since_id:
                    logger.info("Reached Instagram checkpoint: {}. Stopping.", since_id)
                    hit_since = True
                    break
                media_items.extend(self._parse_item_api(item))
                if len(media_items) >= items_needed:
                    break
            
            more_available = feed_data.get("more_available", False)
            next_max_id = feed_data.get("next_max_id")
        
        logger.info("Retrieved {} media items from REST feed for {}", len(media_items), username)
        return media_items

    async def _fetch_graphql(
        self, username: str, since_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[MediaItem]:
        """Fallback: GraphQL web_profile_info — single page only."""
        logger.info("Fetching Instagram profile via GraphQL for user: {}", username)
        max_items = limit if limit is not None else 100
        await self._throttle()
        headers = {
            "User-Agent": self._get_random_ua(),
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/{username}/"
        }
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        resp = await self._fetch_with_retry(url, headers)
        if resp is None:
            return []

        data = resp.json()
        user_data = data.get("data", {}).get("user", {})
        if not user_data:
            return []

        timeline = user_data.get("edge_owner_to_timeline_media", {})
        edges = timeline.get("edges", [])

        media_items: List[MediaItem] = []
        for edge in edges:
            node = edge.get("node", {})
            post_id = node.get("id")
            if since_id and post_id == since_id:
                break
            media_items.extend(self._parse_node(node, username))
            if len(media_items) >= max_items:
                break

        logger.info("Retrieved {} media items from GraphQL for {}", len(media_items), username)
        return media_items

    async def fetch_media_from_url(self, url: str) -> List[MediaItem]:
        """Fetch media from a specific Instagram post URL (e.g. instagram.com/p/C123abc)."""
        shortcode = None
        match = re.search(r'/(p|reel|tv)/([a-zA-Z0-9_-]+)', url)
        if match:
            shortcode = match.group(2)
            
        if not shortcode:
            logger.error("Could not extract Instagram shortcode from URL: {}", url)
            return []
            
        if not self.client:
            await self._create_session()
            
        try:
            # We fetch post details from the official endpoint
            api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
            await self._throttle()
            resp = await self.client.get(api_url)
            if resp.status_code != 200:
                logger.error("Instagram post request failed for shortcode {} (Status {}): {}", shortcode, resp.status_code, resp.text)
                return []
                
            data = resp.json()
            # The structure returned can be inside graphql or directly items
            items_list = data.get("items", [])
            if items_list:
                item_data = items_list[0]
                return self._parse_item_api(item_data)
            
            # graphql structure fallback
            media_node = data.get("graphql", {}).get("shortcode_media", {})
            if media_node:
                author = media_node.get("owner", {}).get("username", "unknown")
                return self._parse_node(media_node, author)
                
            return []
        except Exception as e:
            logger.exception("Error fetching Instagram post URL {}: {}", url, e)
            return []

    def _parse_node(self, node: Dict[str, Any], author: str) -> List[MediaItem]:
        """Parse graphql media node structure."""
        media_items = []
        post_id = node.get("id")
        created_at_ts = node.get("taken_at_timestamp")
        created_at = None
        if created_at_ts:
            from datetime import datetime, timezone
            created_at = datetime.fromtimestamp(created_at_ts, tz=timezone.utc).isoformat()
            
        # Caption text
        text = ""
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        if caption_edges:
            text = caption_edges[0].get("node", {}).get("text", "")
            
        # Extract hashtags from caption
        hashtags = [tag.strip("#") for tag in re.findall(r'#\w+', text)]

        # Check if carousel (multiple images)
        children = node.get("edge_sidecar_to_children", {}).get("edges", [])
        if children:
            for child in children:
                child_node = child.get("node", {})
                media_items.extend(self._parse_node_single(child_node, post_id, author, created_at, text, hashtags))
        else:
            media_items.extend(self._parse_node_single(node, post_id, author, created_at, text, hashtags))
            
        return media_items

    def _parse_node_single(
        self, 
        node: Dict[str, Any], 
        post_id: str, 
        author: str, 
        created_at: Optional[str], 
        text: str, 
        hashtags: List[str]
    ) -> List[MediaItem]:
        is_video = node.get("is_video", False)
        width = node.get("dimensions", {}).get("width")
        height = node.get("dimensions", {}).get("height")
        
        if is_video:
            video_url = node.get("video_url")
            if video_url:
                return [MediaItem(
                    url=video_url,
                    platform="instagram",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.VIDEO,
                    width=width,
                    height=height,
                    original_url=video_url,
                    created_at=created_at,
                    text=text,
                    hashtags=hashtags
                )]
        else:
            display_url = node.get("display_url")
            if display_url:
                return [MediaItem(
                    url=display_url,
                    platform="instagram",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.IMAGE,
                    width=width,
                    height=height,
                    original_url=display_url,
                    created_at=created_at,
                    text=text,
                    hashtags=hashtags
                )]
        return []

    def _parse_item_api(self, item: Dict[str, Any]) -> List[MediaItem]:
        """Parse native items JSON array from direct instagram API endpoints."""
        media_items = []
        post_id = item.get("id")
        created_at_ts = item.get("taken_at")
        created_at = None
        if created_at_ts:
            from datetime import datetime, timezone
            created_at = datetime.fromtimestamp(created_at_ts, tz=timezone.utc).isoformat()
            
        author = item.get("user", {}).get("username", "unknown")
        
        caption_dict = item.get("caption") or {}
        text = caption_dict.get("text", "")
        hashtags = [tag.strip("#") for tag in re.findall(r'#\w+', text)]

        # Check for carousel
        carousel = item.get("carousel_media", [])
        if carousel:
            for child in carousel:
                media_items.extend(self._parse_item_single(child, post_id, author, created_at, text, hashtags))
        else:
            media_items.extend(self._parse_item_single(item, post_id, author, created_at, text, hashtags))
            
        return media_items

    def _parse_item_single(
        self, 
        item: Dict[str, Any], 
        post_id: str, 
        author: str, 
        created_at: Optional[str], 
        text: str, 
        hashtags: List[str]
    ) -> List[MediaItem]:
        media_type_val = item.get("media_type") # 1 = Image, 2 = Video
        width = item.get("original_width")
        height = item.get("original_height")
        
        if media_type_val == 2:
            # Video
            video_versions = item.get("video_versions", [])
            # Select highest resolution video
            if video_versions:
                video_versions.sort(key=lambda x: x.get("width", 0), reverse=True)
                url = video_versions[0].get("url")
                if url:
                    return [MediaItem(
                        url=url,
                        platform="instagram",
                        post_id=post_id,
                        author=author,
                        media_type=MediaType.VIDEO,
                        width=width,
                        height=height,
                        original_url=url,
                        created_at=created_at,
                        text=text,
                        hashtags=hashtags
                    )]
        else:
            # Image
            image_versions = item.get("image_versions2", {}).get("candidates", [])
            if image_versions:
                # First one is usually highest resolution
                url = image_versions[0].get("url")
                if url:
                    return [MediaItem(
                        url=url,
                        platform="instagram",
                        post_id=post_id,
                        author=author,
                        media_type=MediaType.IMAGE,
                        width=width,
                        height=height,
                        original_url=url,
                        created_at=created_at,
                        text=text,
                        hashtags=hashtags
                    )]
        return []
