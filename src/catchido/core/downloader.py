import asyncio
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Any
import httpx
from PIL import Image
from loguru import logger
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, DownloadColumn

from ..db import Database
from ..db.models import MediaItem, IdolProfile, MediaHash, DedupResult
from .dedup import DedupEngine
from .organizer import FileOrganizer

@dataclass
class DownloadReport:
    new_downloaded: int = 0
    skipped_duplicate: int = 0
    replaced_near_duplicate: int = 0
    failed: int = 0

class DownloadManager:
    def __init__(self, config, db: Database):
        self.config = config
        self.db = db
        self.dedup = DedupEngine(
            threshold=config.general.dedup_threshold,
            prefer_higher_res=config.general.prefer_higher_res
        )
        self.semaphore = asyncio.Semaphore(config.general.max_concurrent_downloads)

    async def download_media(self, items: List[MediaItem], idol: IdolProfile) -> DownloadReport:
        """
        Download multiple media items concurrently.
        Integrates deduplication and file organization.
        """
        report = DownloadReport()
        if not items:
            return report

        logger.info("Starting concurrent download of {} items for {}", len(items), idol.display_name)
        
        # Instantiate organizer dynamically for this idol
        base_dir = idol.download_dir or self.config.general.download_dir
        organizer = FileOrganizer(base_dir)
        
        # Ensure target directories exist and write profile metadata
        if idol.download_dir:
            idol_path = Path(idol.download_dir)
        else:
            dummy_path = organizer.get_organized_path(idol, items[0])
            idol_path = dummy_path.parent.parent.parent.parent
            
        organizer.write_profile_json(idol, idol_path)

        # Write group info if applicable (only in global directory mode to avoid polluting parent of custom path)
        if idol.group_name and not idol.download_dir:
            group_path = idol_path.parent
            # List all members of this group in DB
            members = await self.db.list_by_group(idol.group_name)
            if idol.display_name not in [m.display_name for m in members]:
                members.append(idol)
            organizer.write_group_info_json(idol.group_name, members, group_path)

        # Temporary directory for download phase
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Set up rich progress
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TimeRemainingColumn(),
                transient=True
            ) as progress:
                tasks = [
                    self._download_item_task(item, idol, temp_path, progress, report, organizer)
                    for item in items
                ]
                await asyncio.gather(*tasks)

        logger.info(
            "Download finished for {}. New: {}, Replaced: {}, Skipped: {}, Failed: {}",
            idol.display_name, report.new_downloaded, report.replaced_near_duplicate,
            report.skipped_duplicate, report.failed
        )
        return report

    async def _download_item_task(
        self, 
        item: MediaItem, 
        idol: IdolProfile, 
        temp_dir: Path, 
        progress: Progress,
        report: DownloadReport,
        organizer: FileOrganizer
    ):
        async with self.semaphore:
            # 1. Download to temp file
            temp_file_name = f"temp_{item.platform}_{item.post_id}_{random_id()}.tmp"
            temp_file_path = temp_dir / temp_file_name
            
            task_id = progress.add_task(
                description=f"Downloading {item.post_id[:8]}...",
                total=None
            )
            
            success = await self._http_download(item.url, temp_file_path, progress, task_id)
            if not success:
                logger.error("Download failed for URL: {}", item.url)
                report.failed += 1
                progress.remove_task(task_id)
                return

            # 2. Get file properties
            file_size = temp_file_path.stat().st_size
            width, height = None, None
            try:
                with Image.open(temp_file_path) as img:
                    width, height = img.size
            except (OSError, SyntaxError) as e:
                logger.debug("Could not read image dimensions for {}: {}", temp_file_path, e)

            # 3. Deduplication Check
            dedup_res = await self.dedup.check_duplicate(temp_file_path, self.db, width, height)
            
            if dedup_res.is_duplicate and not dedup_res.should_replace:
                # Duplicate exists, skip
                logger.debug("Skipping duplicate: {}", dedup_res.reason)
                report.skipped_duplicate += 1
                try:
                    temp_file_path.unlink()
                except OSError as e:
                    logger.debug("Failed to clean temp file {}: {}", temp_file_path, e)
                progress.remove_task(task_id)
                return

            # 4. Generate organized target path
            # Search for available index if multiple images in same post
            # Since index is not passed, let's try finding next free index filename
            index = 1
            target_path = organizer.get_organized_path(idol, item, index)
            while target_path.exists() and target_path != Path(dedup_res.existing_path or ""):
                index += 1
                target_path = organizer.get_organized_path(idol, item, index)

            # 5. Handle replacement or saving
            try:
                if dedup_res.should_replace and dedup_res.existing_path:
                    # Remove old file
                    old_path = Path(dedup_res.existing_path)
                    if old_path.exists():
                        old_path.unlink()
                        logger.info("Removed lower-res duplicate: {}", old_path)
                    target_path = old_path
                    report.replaced_near_duplicate += 1
                else:
                    report.new_downloaded += 1

                # Move file to final path
                organizer.move_to_organized(temp_file_path, target_path)

                # Compute hashes for DB entry
                sha256 = self.dedup.compute_sha256(target_path)
                phash = self.dedup.compute_phash(target_path)
                dhash = self.dedup.compute_dhash(target_path)

                # 6. Save metadata in DB
                mh = MediaHash(
                    file_path=str(target_path),
                    sha256=sha256,
                    phash=phash,
                    dhash=dhash,
                    width=width,
                    height=height,
                    file_size=file_size,
                    source_url=item.url,
                    source_platform=item.platform,
                    source_user=item.author,
                    idol_name=idol.display_name
                )
                await self.db.add_media_hash(mh)
                
            except Exception as e:
                logger.exception("Error saving final file {}: {}", target_path, e)
                report.failed += 1
                if temp_file_path.exists():
                    try:
                        temp_file_path.unlink()
                    except OSError as e:
                        logger.debug("Failed to clean temp file {}: {}", temp_file_path, e)
            finally:
                progress.remove_task(task_id)

    async def _http_download(self, url: str, target_path: Path, progress: Progress, task_id: Any) -> bool:
        """Download helper with progress updates and retries (incl. 429 backoff)."""
        proxy = None
        if self.config.proxy.enabled:
            proxy = self.config.proxy.https or self.config.proxy.http
            logger.debug("Using configured proxy for downloader: {}", proxy)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=60.0, follow_redirects=True) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code == 429:
                            retry_after = int(response.headers.get("retry-after", 30))
                            logger.warning(
                                "Rate limited (429) on attempt {}/{}. Waiting {}s...",
                                attempt + 1, max_retries, retry_after,
                            )
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_after)
                                continue
                            return False

                        if response.status_code != 200:
                            logger.error("Download URL {} returned status {}", url, response.status_code)
                            if attempt < max_retries - 1:
                                backoff = 2 ** attempt * 5
                                await asyncio.sleep(backoff)
                                continue
                            return False
                            
                        # Set total size on progress bar if header present
                        total_size = int(response.headers.get("content-length", 0))
                        if total_size:
                            progress.update(task_id, total=total_size)
                            
                        with open(target_path, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                f.write(chunk)
                                progress.update(task_id, advance=len(chunk))
                                
                        return True
            except Exception as e:
                logger.warning("Attempt {} failed for download {}: {}", attempt+1, url, e)
                if attempt == max_retries - 1:
                    return False
                await asyncio.sleep(2 ** attempt * 5)
        return False

# Simple helper for random temp names
import uuid
def random_id() -> str:
    return uuid.uuid4().hex[:6]
