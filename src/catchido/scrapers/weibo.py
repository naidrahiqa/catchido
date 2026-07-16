import re
import asyncio
import random
from typing import List, Optional, Dict, Any
from loguru import logger
import httpx

from .base import BaseScraper
from ..db.models import MediaItem, MediaType

class WeiboScraper(BaseScraper):
    def __init__(self, cookie: str, config):
        super().__init__(config)
        self.cookie = cookie
        self.mobile_api = "https://m.weibo.cn/api"

    def get_hd_url(self, url: str) -> str:
        """
        Replace thumbnail/mw2048/bmiddle with 'large' (original resolution).
        Example: https://wx1.sinaimg.cn/mw2048/001abc.jpg -> https://wx1.sinaimg.cn/large/001abc.jpg
        """
        if "sinaimg.cn" not in url:
            return url
            
        # Supported paths: thumbnail, mw2048, bmiddle, orwap, square, mw690
        # We replace the size path part
        url_cleaned = re.sub(r'/(thumbnail|mw2048|bmiddle|orj360|woriginal|mw690)/', '/large/', url)
        return url_cleaned

    async def _create_session(self) -> httpx.AsyncClient:
        client = await super()._create_session()
        # Add weibo headers and cookie
        client.headers.update({
            "Referer": "https://m.weibo.cn/",
            "X-Requested-With": "XMLHttpRequest"
        })
        if self.cookie:
            client.headers["Cookie"] = self.cookie
            logger.debug("Weibo cookie loaded into HTTP headers")
        return client

    async def fetch_media(
        self, 
        query_or_username: str, 
        since_id: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[MediaItem]:
        """
        Scrape Weibo. If query_or_username is pure digits, treat as Weibo UID.
        Otherwise treat as search query.
        """
        if not self.client:
            await self._create_session()

        if query_or_username.isdigit():
            return await self._fetch_user_posts(query_or_username, since_id, limit)
        else:
            return await self._fetch_search_results(query_or_username, since_id, limit)

    async def _fetch_user_posts(self, user_id: str, since_id: Optional[str], limit: Optional[int]) -> List[MediaItem]:
        logger.info("Fetching Weibo posts for user UID: {}", user_id)
        media_items = []
        page = 1
        has_more = True
        
        # Determine container ID for user posts
        try:
            index_url = f"{self.mobile_api}/container/getIndex"
            params = {"type": "uid", "value": user_id}
            
            await self._throttle()
            resp = await self.client.get(index_url, params=params)
            if resp.status_code != 200:
                logger.error("Weibo index request failed for {}: {}", user_id, resp.status_code)
                return []
                
            index_data = resp.json()
            tabs = index_data.get("data", {}).get("tabsInfo", {}).get("tabs", [])
            container_id = None
            for tab in tabs:
                if tab.get("tab_type") == "weibo":
                    container_id = tab.get("containerid")
                    break
                    
            if not container_id:
                # Fallback to general containerid scheme
                container_id = f"107603{user_id}"

            # Fetch pages
            items_needed = limit or 50
            while len(media_items) < items_needed and has_more:
                # Add delay to avoid block
                delay = self.config.weibo.request_delay + random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)
                
                logger.debug("Fetching Weibo page {} for container {}", page, container_id)
                page_url = f"{self.mobile_api}/container/getIndex"
                page_params = {"containerid": container_id, "page": page}
                
                await self._throttle()
                resp = await self.client.get(page_url, params=page_params)
                if resp.status_code != 200:
                    logger.error("Failed to fetch page {} for Weibo user {}", page, user_id)
                    break
                    
                page_data = resp.json()
                cards = page_data.get("data", {}).get("cards", [])
                
                if not cards:
                    has_more = False
                    break
                    
                new_items = self._parse_cards(cards, since_id)
                if not new_items:
                    # If since_id is hit, we stop scraping further pages
                    if since_id and any(card.get("mblog", {}).get("id") == since_id for card in cards):
                        logger.info("Hit Weibo since_id checkpoint: {}. Stopping.", since_id)
                        has_more = False
                    # Or no media on page
                    if page > 5: # safety break
                        has_more = False
                
                media_items.extend(new_items)
                page += 1
                
            return media_items[:items_needed]
        except Exception as e:
            logger.exception("Error fetching Weibo UID {}: {}", user_id, e)
            return []

    async def _fetch_search_results(self, query: str, since_id: Optional[str], limit: Optional[int]) -> List[MediaItem]:
        logger.info("Searching Weibo for: {}", query)
        if not self.client:
            await self._create_session()
            
        try:
            search_url = f"{self.mobile_api}/container/getIndex"
            params = {
                "containerid": f"100103type=1&q={query}",
                "page_type": "search"
            }
            await self._throttle()
            resp = await self.client.get(search_url, params=params)
            if resp.status_code != 200:
                logger.error("Weibo search request failed: {}", resp.status_code)
                return []
                
            search_data = resp.json()
            cards = search_data.get("data", {}).get("cards", [])
            
            # Find the card containing the search result list
            result_cards = []
            for card in cards:
                if card.get("card_type") == 11: # Card type 11 holds sub-cards
                    result_cards.extend(card.get("card_group", []))
                elif card.get("card_type") == 9: # Card type 9 is direct mblog
                    result_cards.append(card)
                    
            return self._parse_cards(result_cards, since_id)[:(limit or 50)]
        except Exception as e:
            logger.exception("Error searching Weibo for {}: {}", query, e)
            return []

    async def fetch_media_from_url(self, url: str) -> List[MediaItem]:
        """Fetch media from a specific Weibo detail page (e.g. /detail/123456)."""
        # Weibo URLs can be m.weibo.cn/status/49876543210 or weibo.com/12345678/JklmNopq
        # We can extract the post ID from detail/ or status/
        post_id = None
        match = re.search(r'/(detail|status)/([a-zA-Z0-9]+)', url)
        if match:
            post_id = match.group(2)
        else:
            # Try tailing digits
            match_tail = re.search(r'/([0-9]{10,20})', url)
            if match_tail:
                post_id = match_tail.group(1)

        if not post_id:
            logger.error("Could not extract Weibo post ID from URL: {}", url)
            return []
            
        if not self.client:
            await self._create_session()
            
        try:
            detail_url = f"{self.mobile_api}/statuses/show"
            params = {"id": post_id}
            await self._throttle()
            resp = await self.client.get(detail_url, params=params)
            if resp.status_code != 200:
                logger.error("Weibo detail request failed for ID {}: {}", post_id, resp.status_code)
                return []
                
            resp_data = resp.json()
            mblog = resp_data.get("data")
            if not mblog:
                logger.error("Weibo post details not found for ID {}", post_id)
                return []
                
            return self._parse_mblog(mblog)
        except Exception as e:
            logger.exception("Error getting Weibo URL {}: {}", url, e)
            return []

    def _parse_cards(self, cards: List[Dict[str, Any]], since_id: Optional[str] = None) -> List[MediaItem]:
        media_items = []
        for card in cards:
            if card.get("card_type") != 9:
                continue
                
            mblog = card.get("mblog", {})
            post_id = mblog.get("id")
            
            if since_id and post_id == since_id:
                logger.info("Reached since_id checkpoint: {}. Stopping parse.", since_id)
                break
                
            media_items.extend(self._parse_mblog(mblog))
        return media_items

    def _parse_mblog(self, mblog: Dict[str, Any]) -> List[MediaItem]:
        media_items = []
        post_id = mblog.get("id")
        created_at = mblog.get("created_at")
        text = mblog.get("text", "")
        
        # Clean HTML tags from text
        clean_text = re.sub(r'<[^>]+>', '', text)
        
        # Extract hashtags
        hashtags = [tag.strip("#") for tag in re.findall(r'#([^#]+)#', text)]
        
        # Author info
        user_info = mblog.get("user", {})
        author = user_info.get("screen_name", user_info.get("idstr", "unknown"))

        # Image extraction
        pics = mblog.get("pics", [])
        for idx, pic in enumerate(pics):
            large_url = pic.get("large", {}).get("url")
            orig_url = pic.get("url")
            
            if large_url:
                media_items.append(MediaItem(
                    url=self.get_hd_url(large_url),
                    platform="weibo",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.IMAGE,
                    width=pic.get("large", {}).get("geo", {}).get("width"),
                    height=pic.get("large", {}).get("geo", {}).get("height"),
                    original_url=orig_url,
                    created_at=created_at,
                    text=clean_text,
                    hashtags=hashtags
                ))

        # Video extraction
        # Weibo stores video in page_info structure
        page_info = mblog.get("page_info", {})
        if page_info.get("type") == "video":
            video_url = None
            urls = page_info.get("media_info", {}).get("stream_url_hd") or page_info.get("media_info", {}).get("stream_url")
            if urls:
                video_url = urls
            
            # Alternative urls structure
            if not video_url:
                playback_list = page_info.get("media_info", {}).get("playback_list", [])
                if playback_list:
                    # Get highest definition
                    playback_list.sort(key=lambda x: x.get("play_info", {}).get("bitrate", 0), reverse=True)
                    video_url = playback_list[0].get("play_info", {}).get("play_url")
            
            if video_url:
                media_items.append(MediaItem(
                    url=video_url,
                    platform="weibo",
                    post_id=post_id,
                    author=author,
                    media_type=MediaType.VIDEO,
                    original_url=video_url,
                    created_at=created_at,
                    text=clean_text,
                    hashtags=hashtags
                ))
                
        return media_items
