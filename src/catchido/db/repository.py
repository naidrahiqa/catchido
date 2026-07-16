import json
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import aiosqlite
from loguru import logger

from .models import (
    IdolType, IdolStatus, MediaSourceType, MediaType,
    IdolProfile, IdolKeywordEntry, TrustedAccount,
    MediaHash, MediaItem, DownloadCheckpoint
)

class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    async def __aenter__(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, '_conn') and self._conn is not None:
            await self._conn.close()

    async def close(self):
        if hasattr(self, '_conn'):
            await self._conn.close()

    async def initialize(self):
        """Create all tables and indexes if they don't exist."""
        logger.info("Initializing database at {}", self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for performance
            await db.execute("PRAGMA journal_mode=WAL")
            
            # 1. idol_profiles
            await db.execute("""
            CREATE TABLE IF NOT EXISTS idol_profiles (
                id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL UNIQUE,
                idol_type TEXT NOT NULL,
                kanji_name TEXT,
                generation TEXT,
                team TEXT,
                hangul_name TEXT,
                stage_name TEXT,
                real_name TEXT,
                positions TEXT, -- JSON array
                group_name TEXT,
                sub_unit TEXT,
                company TEXT,
                fandom_name TEXT,
                birthday TEXT,
                debut_date TEXT,
                graduation_date TEXT,
                status TEXT DEFAULT 'active',
                blood_type TEXT,
                birthplace TEXT,
                official_color TEXT,
                official_twitter TEXT,
                official_instagram TEXT,
                official_weibo TEXT,
                official_tiktok TEXT,
                download_dir TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Legacy migration: add download_dir if missing (pre-v0.2 databases)
            try:
                await db.execute("ALTER TABLE idol_profiles ADD COLUMN download_dir TEXT")
                await db.commit()
            except Exception:
                pass

            # 2. idol_keywords
            await db.execute("""
            CREATE TABLE IF NOT EXISTS idol_keywords (
                id INTEGER PRIMARY KEY,
                idol_name TEXT NOT NULL,
                idol_type TEXT NOT NULL,
                keyword TEXT NOT NULL,
                script_type TEXT,
                platform TEXT DEFAULT 'all',
                is_auto_generated BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                hit_count INTEGER DEFAULT 0,
                last_used_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(idol_name, keyword, platform)
            )
            """)

            # 3. trusted_accounts
            await db.execute("""
            CREATE TABLE IF NOT EXISTS trusted_accounts (
                id INTEGER PRIMARY KEY,
                idol_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                username TEXT NOT NULL,
                account_type TEXT DEFAULT 'fansite',
                is_auto_discovered BOOLEAN DEFAULT FALSE,
                media_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(idol_name, platform, username)
            )
            """)

            # 4. media_hashes
            await db.execute("""
            CREATE TABLE IF NOT EXISTS media_hashes (
                id INTEGER PRIMARY KEY,
                file_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                phash TEXT,
                dhash TEXT,
                width INTEGER,
                height INTEGER,
                file_size INTEGER,
                source_url TEXT,
                source_platform TEXT,
                source_user TEXT,
                idol_name TEXT,
                downloaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 5. download_checkpoints
            await db.execute("""
            CREATE TABLE IF NOT EXISTS download_checkpoints (
                id INTEGER PRIMARY KEY,
                idol_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_username TEXT NOT NULL,
                last_id TEXT NOT NULL,
                last_checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(idol_name, platform, source_username)
            )
            """)

            # Indexes
            await db.execute("CREATE INDEX IF NOT EXISTS idx_profile_group ON idol_profiles(group_name)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_profile_type ON idol_profiles(idol_type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_profile_company ON idol_profiles(company)")
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_keyword_idol ON idol_keywords(idol_name)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_keyword_platform ON idol_keywords(platform)")
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trusted_platform ON trusted_accounts(platform, idol_name)")
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media_hashes(sha256)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_phash ON media_hashes(phash)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_idol ON media_hashes(idol_name)")
            
            await db.commit()

    # --- Idol Profile Operations ---
    
    async def add_idol(self, profile: IdolProfile) -> bool:
        try:
            positions_json = json.dumps(profile.positions)
            await self._conn.execute("""
            INSERT OR REPLACE INTO idol_profiles (
                display_name, idol_type, kanji_name, generation, team,
                hangul_name, stage_name, real_name, positions, group_name,
                sub_unit, company, fandom_name, birthday, debut_date,
                graduation_date, status, blood_type, birthplace, official_color,
                official_twitter, official_instagram, official_weibo, official_tiktok,
                download_dir
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile.display_name, profile.idol_type.value, profile.kanji_name, profile.generation, profile.team,
                profile.hangul_name, profile.stage_name, profile.real_name, positions_json, profile.group_name,
                profile.sub_unit, profile.company, profile.fandom_name, profile.birthday, profile.debut_date,
                profile.graduation_date, profile.status.value, profile.blood_type, profile.birthplace, profile.official_color,
                profile.official_twitter, profile.official_instagram, profile.official_weibo, profile.official_tiktok,
                profile.download_dir
            ))
            await self._conn.commit()
            return True
        except Exception as e:
            logger.error("Error adding idol {}: {}", profile.display_name, e)
            return False

    async def get_idol(self, name: str) -> Optional[IdolProfile]:
        async with self._conn.execute(
            "SELECT * FROM idol_profiles WHERE display_name = ?", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_profile(row)
        return None

    async def update_idol(self, name: str, profile: IdolProfile) -> bool:
        try:
            positions_json = json.dumps(profile.positions)
            await self._conn.execute("""
            UPDATE idol_profiles SET
                display_name=?, idol_type=?, kanji_name=?, generation=?, team=?,
                hangul_name=?, stage_name=?, real_name=?, positions=?, group_name=?,
                sub_unit=?, company=?, fandom_name=?, birthday=?, debut_date=?,
                graduation_date=?, status=?, blood_type=?, birthplace=?, official_color=?,
                official_twitter=?, official_instagram=?, official_weibo=?, official_tiktok=?,
                download_dir=?, updated_at=CURRENT_TIMESTAMP
            WHERE display_name=?
            """, (
                profile.display_name, profile.idol_type.value, profile.kanji_name, profile.generation, profile.team,
                profile.hangul_name, profile.stage_name, profile.real_name, positions_json, profile.group_name,
                profile.sub_unit, profile.company, profile.fandom_name, profile.birthday, profile.debut_date,
                profile.graduation_date, profile.status.value, profile.blood_type, profile.birthplace, profile.official_color,
                profile.official_twitter, profile.official_instagram, profile.official_weibo, profile.official_tiktok,
                profile.download_dir, name
            ))
            await self._conn.commit()
            return True
        except Exception as e:
            logger.error("Error updating idol {}: {}", name, e)
            return False

    async def delete_trusted_accounts_for_idol(self, idol_name: str) -> None:
        await self._conn.execute("DELETE FROM trusted_accounts WHERE idol_name = ?", (idol_name,))
        await self._conn.commit()

    async def delete_idol(self, name: str) -> bool:
        try:
            await self._conn.execute("DELETE FROM idol_profiles WHERE display_name = ?", (name,))
            await self._conn.execute("DELETE FROM idol_keywords WHERE idol_name = ?", (name,))
            await self._conn.execute("DELETE FROM trusted_accounts WHERE idol_name = ?", (name,))
            await self._conn.execute("DELETE FROM download_checkpoints WHERE idol_name = ?", (name,))
            await self._conn.commit()
            return True
        except Exception as e:
            logger.error("Error deleting idol {}: {}", name, e)
            return False

    async def list_idols(self) -> List[IdolProfile]:
        async with self._conn.execute("SELECT * FROM idol_profiles ORDER BY display_name") as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_profile(r) for r in rows]

    async def list_by_group(self, group_name: str) -> List[IdolProfile]:
        async with self._conn.execute(
            "SELECT * FROM idol_profiles WHERE group_name LIKE ? ORDER BY display_name",
            (f"%{group_name}%",)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_profile(r) for r in rows]

    async def list_by_type(self, type_str: str) -> List[IdolProfile]:
        async with self._conn.execute(
            "SELECT * FROM idol_profiles WHERE idol_type = ? ORDER BY display_name", (type_str,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_profile(r) for r in rows]

    async def list_by_company(self, company: str) -> List[IdolProfile]:
        async with self._conn.execute(
            "SELECT * FROM idol_profiles WHERE company LIKE ? ORDER BY display_name",
            (f"%{company}%",)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_profile(r) for r in rows]

    def _row_to_profile(self, row) -> IdolProfile:
        positions = []
        if row["positions"]:
            try:
                positions = json.loads(row["positions"])
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Failed to parse positions JSON: {}", e)
        return IdolProfile(
            display_name=row["display_name"],
            idol_type=IdolType(row["idol_type"]),
            kanji_name=row["kanji_name"],
            generation=row["generation"],
            team=row["team"],
            hangul_name=row["hangul_name"],
            stage_name=row["stage_name"],
            real_name=row["real_name"],
            positions=positions,
            group_name=row["group_name"],
            sub_unit=row["sub_unit"],
            company=row["company"],
            fandom_name=row["fandom_name"],
            birthday=row["birthday"],
            debut_date=row["debut_date"],
            graduation_date=row["graduation_date"],
            status=IdolStatus(row["status"]),
            blood_type=row["blood_type"],
            birthplace=row["birthplace"],
            official_color=row["official_color"],
            official_twitter=row["official_twitter"],
            official_instagram=row["official_instagram"],
            official_weibo=row["official_weibo"],
            official_tiktok=row["official_tiktok"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            download_dir=row["download_dir"] if "download_dir" in row.keys() else None
        )

    # --- Keyword Operations ---

    async def add_keyword(self, entry: IdolKeywordEntry) -> bool:
        try:
            await self._conn.execute("""
            INSERT OR IGNORE INTO idol_keywords (
                idol_name, idol_type, keyword, script_type, platform,
                is_auto_generated, is_active, hit_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.idol_name, entry.idol_type.value, entry.keyword, entry.script_type,
                entry.platform, entry.is_auto_generated, entry.is_active, entry.hit_count
            ))
            await self._conn.commit()
            return True
        except Exception as e:
            logger.error("Error adding keyword {} for idol {}: {}", entry.keyword, entry.idol_name, e)
            return False

    async def get_keywords_for_idol(self, idol_name: str, active_only: bool = True) -> List[IdolKeywordEntry]:
        query = "SELECT * FROM idol_keywords WHERE idol_name = ?"
        if active_only:
            query += " AND is_active = 1"
        async with self._conn.execute(query, (idol_name,)) as cursor:
            rows = await cursor.fetchall()
            return [
                IdolKeywordEntry(
                    idol_name=row["idol_name"],
                    idol_type=IdolType(row["idol_type"]),
                    keyword=row["keyword"],
                    script_type=row["script_type"],
                    platform=row["platform"],
                    is_auto_generated=bool(row["is_auto_generated"]),
                    is_active=bool(row["is_active"]),
                    hit_count=row["hit_count"],
                    last_used_at=row["last_used_at"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]

    async def update_hit_count(self, idol_name: str, keyword: str, platform: str) -> None:
        await self._conn.execute("""
        UPDATE idol_keywords
        SET hit_count = hit_count + 1, last_used_at = CURRENT_TIMESTAMP
        WHERE idol_name = ? AND keyword = ? AND platform = ?
        """, (idol_name, keyword, platform))
        await self._conn.commit()

    async def toggle_keyword_active(self, idol_name: str, keyword: str, active: bool) -> None:
        await self._conn.execute("""
        UPDATE idol_keywords
        SET is_active = ?
        WHERE idol_name = ? AND keyword = ?
        """, (1 if active else 0, idol_name, keyword))
        await self._conn.commit()

    # --- Trusted Account Operations ---

    async def add_trusted_account(self, acc: TrustedAccount) -> bool:
        try:
            await self._conn.execute("""
            INSERT OR REPLACE INTO trusted_accounts (
                idol_name, platform, username, account_type, is_auto_discovered, media_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                acc.idol_name, acc.platform, acc.username, acc.account_type,
                acc.is_auto_discovered, acc.media_count
            ))
            await self._conn.commit()
            return True
        except Exception as e:
            logger.error("Error adding trusted account {}: {}", acc.username, e)
            return False

    async def get_trusted_accounts(self, idol_name: str) -> List[TrustedAccount]:
        async with self._conn.execute(
            "SELECT * FROM trusted_accounts WHERE idol_name = ?", (idol_name,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                TrustedAccount(
                    idol_name=row["idol_name"],
                    platform=row["platform"],
                    username=row["username"],
                    account_type=row["account_type"],
                    is_auto_discovered=bool(row["is_auto_discovered"]),
                    media_count=row["media_count"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]

    async def is_trusted(self, platform: str, username: str, idol_name: str) -> bool:
        async with self._conn.execute("""
        SELECT COUNT(*) FROM trusted_accounts 
        WHERE platform = ? AND (username = ? OR username = '@' || ?) AND idol_name = ?
        """, (platform, username, username, idol_name)) as cursor:
            row = await cursor.fetchone()
            return row[0] > 0 if row else False

    # --- Media Hash Operations ---

    async def add_media_hash(self, mh: MediaHash) -> bool:
        try:
            await self._conn.execute("""
            INSERT OR REPLACE INTO media_hashes (
                file_path, sha256, phash, dhash, width, height, file_size,
                source_url, source_platform, source_user, idol_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mh.file_path, mh.sha256, mh.phash, mh.dhash, mh.width, mh.height, mh.file_size,
                mh.source_url, mh.source_platform, mh.source_user, mh.idol_name
            ))
            await self._conn.commit()
            return True
        except Exception as e:
            logger.error("Error adding media hash for {}: {}", mh.file_path, e)
            return False

    async def check_sha256_exists(self, sha256: str) -> Optional[str]:
        async with self._conn.execute(
            "SELECT file_path FROM media_hashes WHERE sha256 = ?", (sha256,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row["file_path"]
        return None

    async def find_similar_phash(self, phash: str, threshold: int = 5) -> List[Tuple[str, int, int, int]]:
        """
        Query for potential perceptual duplicates.
        Returns List of (file_path, hamming_distance, width, height)
        """
        if not phash:
            return []
        
        # In a real database we would load all hashes or use a specialized query.
        # Since SQLite doesn't have native Hamming distance functions, we load
        # entries and compute the distance in Python.
        # For optimization, we can filter by the same idol_name if needed.
        async with self._conn.execute("SELECT file_path, phash, width, height FROM media_hashes WHERE phash IS NOT NULL") as cursor:
            rows = await cursor.fetchall()
            
        results = []
        val1 = int(phash, 16)
        for row in rows:
            try:
                val2 = int(row["phash"], 16)
                # Hamming distance between two integers
                dist = bin(val1 ^ val2).count('1')
                if dist <= threshold:
                    results.append((row["file_path"], dist, row["width"], row["height"]))
            except ValueError:
                continue
                
        # Sort by distance (closest first)
        results.sort(key=lambda x: x[1])
        return results

    async def get_media_count(self, idol_name: Optional[str] = None) -> int:
        if idol_name:
            async with self._conn.execute(
                "SELECT COUNT(*) FROM media_hashes WHERE idol_name = ?", (idol_name,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
        else:
            async with self._conn.execute("SELECT COUNT(*) FROM media_hashes") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # --- Checkpoint Operations ---

    async def get_checkpoint(self, idol_name: str, platform: str, source_username: str) -> Optional[str]:
        async with self._conn.execute("""
        SELECT last_id FROM download_checkpoints
        WHERE idol_name = ? AND platform = ? AND source_username = ?
        """, (idol_name, platform, source_username)) as cursor:
            row = await cursor.fetchone()
            return row["last_id"] if row else None

    async def update_checkpoint(self, checkpoint: DownloadCheckpoint) -> None:
        await self._conn.execute("""
        INSERT OR REPLACE INTO download_checkpoints (
            idol_name, platform, source_username, last_id, last_checked_at
        ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            checkpoint.idol_name, checkpoint.platform, checkpoint.source_username, checkpoint.last_id
        ))
        await self._conn.commit()

    # --- Statistics Operations ---

    async def get_download_stats(self) -> Dict[str, Any]:
        async with self._conn.execute("SELECT COUNT(*), SUM(file_size) FROM media_hashes") as cursor:
            row = await cursor.fetchone()
            total_count = row[0] if row else 0
            total_size = row[1] if row and row[1] else 0

        async with self._conn.execute(
            "SELECT source_platform, COUNT(*), SUM(file_size) FROM media_hashes GROUP BY source_platform"
        ) as cursor:
            platform_rows = await cursor.fetchall()
            platform_stats = {
                r[0]: {"count": r[1], "size": r[2] or 0} for r in platform_rows
            }

        return {
            "total_count": total_count,
            "total_size": total_size,
            "platforms": platform_stats
        }

    async def get_stats_by_idol(self, idol_name: str) -> Dict[str, Any]:
        async with self._conn.execute(
            "SELECT COUNT(*), SUM(file_size) FROM media_hashes WHERE idol_name = ?", (idol_name,)
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0
            size = row[1] if row and row[1] else 0
        return {"count": count, "size": size}

    async def get_stats_by_group(self, group_name: str) -> Dict[str, Any]:
        async with self._conn.execute("""
        SELECT COUNT(mh.id), SUM(mh.file_size)
        FROM media_hashes mh
        JOIN idol_profiles ip ON mh.idol_name = ip.display_name
        WHERE ip.group_name LIKE ?
        """, (f"%{group_name}%",)) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0
            size = row[1] if row and row[1] else 0
        return {"count": count, "size": size}
