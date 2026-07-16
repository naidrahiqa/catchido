import re
from typing import List, Optional, Dict, Any
from loguru import logger
import httpx

from .base import BaseScraper
from ..db.models import MediaItem, MediaType

class TwitterScraper(BaseScraper):
    def __init__(self, bearer_token: str, config):
        super().__init__(config, request_delay=config.twitter.request_delay)
        self.bearer_token = bearer_token
        self.api_base = "https://api.twitter.com/2"

    def get_hd_url(self, url: str) -> str:
        """
        Append format and name=4096x4096 to get original high resolution.
        Input: https://pbs.twimg.com/media/F123abc.jpg
        Output: https://pbs.twimg.com/media/F123abc?format=jpg&name=4096x4096
        """
        if "pbs.twimg.com/media/" not in url:
            return url
            
        # Parse out format if already specified in URL suffix
        parsed_url = url.split('?')[0]
        match = re.search(r'\.(\w+)$', parsed_url)
        fmt = match.group(1) if match else "jpg"
        
        # Remove suffix
        base_url = re.sub(r'\.\w+$', '', parsed_url)
        return f"{base_url}?format={fmt}&name=4096x4096"

    def _get_best_video_variant(self, variants: List[Dict[str, Any]]) -> Optional[str]:
        """Get the URL of the highest bitrate video variant."""
        best_url = None
        max_bitrate = -1
        
        for var in variants:
            if var.get("content_type") == "video/mp4":
                bitrate = var.get("bitrate", 0)
                if bitrate > max_bitrate:
                    max_bitrate = bitrate
                    best_url = var.get("url")
                    
        return best_url or (variants[0].get("url") if variants else None)

    async def fetch_media(
        self, 
        query_or_username: str, 
        since_id: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[MediaItem]:
        """
        Fetch media either from a user (if prefixed with '@') or via search query.
        """
        if not self.bearer_token:
            logger.warning("Twitter Bearer Token is not configured. Skipping Twitter scrape.")
            return []

        if not self.client:
            await self._create_session()

        # Add auth header
        self.client.headers["Authorization"] = f"Bearer {self.bearer_token}"

        if query_or_username.startswith("@"):
            username = query_or_username.lstrip("@")
            return await self._fetch_user_timeline(username, since_id, limit)
        else:
            return await self._fetch_search(query_or_username, since_id, limit)

    async def _fetch_user_timeline(self, username: str, since_id: Optional[str], limit: Optional[int]) -> List[MediaItem]:
        logger.info("Fetching Twitter timeline for user: {}", username)
        try:
            # 1. Get user ID
            user_url = f"{self.api_base}/users/by/username/{username}"
            await self._throttle()
            resp = await self.client.get(user_url)
            if resp.status_code != 200:
                logger.error("Failed to get Twitter user ID for {}: {}", username, resp.text)
                return []
                
            user_data = resp.json()
            if "data" not in user_data:
                logger.error("User {} not found on Twitter", username)
                return []
                
            user_id = user_data["data"]["id"]
            
            # 2. Get tweets with media expansions
            tweets_url = f"{self.api_base}/users/{user_id}/tweets"
            params = {
                "max_results": min(limit or 100, 100),
                "expansions": "attachments.media_keys",
                "media.fields": "type,url,width,height,variants",
                "tweet.fields": "created_at,text"
            }
            if since_id:
                params["since_id"] = since_id
                
            await self._throttle()
            resp = await self.client.get(tweets_url, params=params)
            if resp.status_code != 200:
                logger.error("Failed to get tweets for {}: {}", username, resp.text)
                return []
                
            return self._parse_api_response(resp.json(), username)
        except Exception as e:
            logger.exception("Error scraping Twitter user {}: {}", username, e)
            return []

    async def _fetch_search(self, query: str, since_id: Optional[str], limit: Optional[int]) -> List[MediaItem]:
        logger.info("Searching Twitter for query: {}", query)
        try:
            search_url = f"{self.api_base}/tweets/search/recent"
            params = {
                "query": query,
                "max_results": min(limit or 100, 100),
                "expansions": "attachments.media_keys",
                "media.fields": "type,url,width,height,variants",
                "tweet.fields": "created_at,text"
            }
            if since_id:
                params["since_id"] = since_id
                
            await self._throttle()
            resp = await self.client.get(search_url, params=params)
            if resp.status_code != 200:
                logger.error("Failed Twitter search: {}", resp.text)
                return []
                
            return self._parse_api_response(resp.json())
        except Exception as e:
            logger.exception("Error searching Twitter: {}", e)
            return []

    async def fetch_media_from_url(self, url: str) -> List[MediaItem]:
        """Fetch media directly from a single tweet status URL."""
        if not self.bearer_token:
            logger.warning("Twitter Bearer Token is not configured.")
            return []
            
        tweet_id_match = re.search(r'status/(\d+)', url)
        if not tweet_id_match:
            logger.error("Invalid Tweet URL: {}", url)
            return []
            
        tweet_id = tweet_id_match.group(1)
        if not self.client:
            await self._create_session()
            
        self.client.headers["Authorization"] = f"Bearer {self.bearer_token}"
        
        try:
            tweet_url = f"{self.api_base}/tweets/{tweet_id}"
            params = {
                "expansions": "attachments.media_keys,author_id",
                "media.fields": "type,url,width,height,variants",
                "tweet.fields": "created_at,text"
            }
            await self._throttle()
            resp = await self.client.get(tweet_url, params=params)
            if resp.status_code != 200:
                logger.error("Failed to fetch tweet details for ID {}: {}", tweet_id, resp.text)
                return []
                
            return self._parse_api_response(resp.json())
        except Exception as e:
            logger.exception("Error getting tweet URL {}: {}", url, e)
            return []

    def _parse_api_response(self, response_data: Dict[str, Any], default_author: str = "unknown") -> List[MediaItem]:
        """Parse Twitter API expansion structure to extract MediaItems."""
        media_items = []
        if "data" not in response_data:
            return []
            
        # Map media_key to media object details
        media_map = {}
        includes = response_data.get("includes", {})
        for media in includes.get("media", []):
            media_map[media["media_key"]] = media
            
        tweets = response_data["data"]
        if not isinstance(tweets, list):
            tweets = [tweets]
            
        for tweet in tweets:
            tweet_id = tweet["id"]
            text = tweet.get("text", "")
            created_at = tweet.get("created_at")
            
            # Extract hashtags from text
            hashtags = [tag.strip("#") for tag in re.findall(r'#\w+', text)]
            
            attachments = tweet.get("attachments", {})
            media_keys = attachments.get("media_keys", [])
            
            for idx, key in enumerate(media_keys):
                media_info = media_map.get(key)
                if not media_info:
                    continue
                    
                m_type = media_info.get("type")
                width = media_info.get("width")
                height = media_info.get("height")
                
                if m_type == "photo":
                    url = media_info.get("url")
                    if url:
                        media_items.append(MediaItem(
                            url=self.get_hd_url(url),
                            platform="twitter",
                            post_id=tweet_id,
                            author=default_author,
                            media_type=MediaType.IMAGE,
                            width=width,
                            height=height,
                            original_url=url,
                            created_at=created_at,
                            text=text,
                            hashtags=hashtags
                        ))
                elif m_type == "video" or m_type == "animated_gif":
                    variants = media_info.get("variants", [])
                    url = self._get_best_video_variant(variants)
                    if url:
                        media_items.append(MediaItem(
                            url=url,
                            platform="twitter",
                            post_id=tweet_id,
                            author=default_author,
                            media_type=MediaType.VIDEO,
                            width=width,
                            height=height,
                            original_url=url,
                            created_at=created_at,
                            text=text,
                            hashtags=hashtags
                        ))
        return media_items
