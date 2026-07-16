import asyncio
import time
import random
from abc import ABC, abstractmethod
from typing import List, Optional
import httpx
from loguru import logger

from ..db.models import MediaItem

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

class BaseScraper(ABC):
    def __init__(self, config, request_delay: float = 2.0):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
        self._request_delay = request_delay
        self._last_request_time = 0.0

    async def _throttle(self):
        """Proactive rate limiter — enforce minimum delay between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._request_delay:
            wait = self._request_delay - elapsed + random.uniform(0.1, 0.5)
            logger.debug("Throttling: waiting {:.2f}s", wait)
            await asyncio.sleep(wait)
        self._last_request_time = time.monotonic()

    async def _create_session(self) -> httpx.AsyncClient:
        """Create async HTTP client with proxies if configured."""
        headers = {
            "User-Agent": self._get_random_ua(),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        proxy = None
        if self.config.proxy.enabled:
            proxy = self.config.proxy.https or self.config.proxy.http
            logger.debug("Using configured proxy for scraper: {}", proxy)

        self.client = httpx.AsyncClient(
            headers=headers,
            proxy=proxy,
            timeout=30.0,
            follow_redirects=True,
            http2=True
        )
        return self.client

    def _get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def _rate_limit_wait(self, retry_count: int):
        """Exponential backoff wait."""
        wait_time = (2 ** retry_count) + random.uniform(0.5, 1.5)
        logger.warning("Rate limited. Waiting {:.2f}s before retry...", wait_time)
        await asyncio.sleep(wait_time)

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    @abstractmethod
    async def fetch_media(
        self, 
        query_or_username: str, 
        since_id: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[MediaItem]:
        """Fetch media items from the platform."""
        pass

    @abstractmethod
    async def fetch_media_from_url(self, url: str) -> List[MediaItem]:
        """Fetch media items directly from a specific post URL."""
        pass

    @abstractmethod
    def get_hd_url(self, url: str) -> str:
        """Transform a media URL to its highest resolution variant."""
        pass
