import hashlib
from pathlib import Path
from typing import Optional
from PIL import Image
import imagehash
from loguru import logger

from ..db import Database
from ..db.models import DedupResult

class DedupEngine:
    def __init__(self, threshold: int = 5, prefer_higher_res: bool = True):
        self.threshold = threshold
        self.prefer_higher_res = prefer_higher_res

    def compute_sha256(self, file_path: Path | str) -> str:
        """Compute the SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def compute_phash(self, file_path: Path | str) -> Optional[str]:
        """Compute the perceptual hash (pHash) of an image."""
        try:
            with Image.open(file_path) as img:
                return str(imagehash.phash(img))
        except Exception as e:
            logger.debug("Failed to compute pHash for {}: {}", file_path, e)
            return None

    def compute_dhash(self, file_path: Path | str) -> Optional[str]:
        """Compute the difference hash (dHash) of an image."""
        try:
            with Image.open(file_path) as img:
                return str(imagehash.dhash(img))
        except Exception as e:
            logger.debug("Failed to compute dHash for {}: {}", file_path, e)
            return None

    def hamming_distance(self, hash1: str, hash2: str) -> int:
        """Compute Hamming distance between two hex hashes."""
        try:
            return bin(int(hash1, 16) ^ int(hash2, 16)).count('1')
        except Exception:
            return 999  # Safe large distance

    async def check_duplicate(self, file_path: Path | str, db: Database, new_width: Optional[int] = None, new_height: Optional[int] = None) -> DedupResult:
        """
        Check if the file is a duplicate (SHA-256) or near-duplicate (pHash)
        against existing records in the database.
        """
        p = Path(file_path)
        if not p.exists():
            return DedupResult(is_duplicate=False, is_near_duplicate=False, reason="File not found")

        # 1. Exact SHA-256 check
        sha256 = self.compute_sha256(p)
        existing_path_sha = await db.check_sha256_exists(sha256)
        if existing_path_sha:
            # Check if file still exists on disk
            if Path(existing_path_sha).exists():
                return DedupResult(
                    is_duplicate=True,
                    is_near_duplicate=False,
                    existing_path=existing_path_sha,
                    should_replace=False,
                    reason="Exact SHA-256 match"
                )

        # 2. Perceptual check (for images only)
        suffix = p.suffix.lower()
        is_image = suffix in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']
        if not is_image:
            return DedupResult(is_duplicate=False, is_near_duplicate=False)

        phash = self.compute_phash(p)
        if not phash:
            return DedupResult(is_duplicate=False, is_near_duplicate=False)

        # Get actual image dimensions if not passed
        if not new_width or not new_height:
            try:
                with Image.open(p) as img:
                    new_width, new_height = img.size
            except:
                pass

        new_resolution = (new_width or 0) * (new_height or 0)

        # Find potential perceptual duplicates in DB
        similar_items = await db.find_similar_phash(phash, self.threshold)
        for existing_path, dist, ext_width, ext_height in similar_items:
            if not Path(existing_path).exists():
                continue # Skip dead paths

            ext_resolution = (ext_width or 0) * (ext_height or 0)
            
            # Near duplicate found
            if self.prefer_higher_res and new_resolution > ext_resolution:
                logger.info(
                    "Near duplicate found: {} ({}x{}) has lower resolution than new file {} ({}x{}). Will replace.",
                    existing_path, ext_width, ext_height, p.name, new_width, new_height
                )
                return DedupResult(
                    is_duplicate=False,
                    is_near_duplicate=True,
                    existing_path=existing_path,
                    should_replace=True,
                    reason=f"Near duplicate with higher resolution (Hamming dist: {dist})"
                )
            else:
                logger.debug(
                    "Near duplicate skipped: {} ({}x{}) has higher/equal resolution than new file {} ({}x{}).",
                    existing_path, ext_width, ext_height, p.name, new_width, new_height
                )
                return DedupResult(
                    is_duplicate=True,
                    is_near_duplicate=True,
                    existing_path=existing_path,
                    should_replace=False,
                    reason=f"Near duplicate with lower/equal resolution (Hamming dist: {dist})"
                )

        return DedupResult(is_duplicate=False, is_near_duplicate=False)
