import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger

from ..db.models import IdolProfile, MediaItem, IdolType
from ..utils.helpers import sanitize_filename, get_file_extension, ensure_dir

class FileOrganizer:
    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def generate_filename(self, media_item: MediaItem, index: int = 1) -> str:
        """
        Generate file name according to conventions:
        {source_user}_{post_id}_{index}.{ext}
        """
        user = sanitize_filename(media_item.author or "unknown")
        post_id = sanitize_filename(media_item.post_id)
        ext = get_file_extension(media_item.url)
        return f"{user}_{post_id}_{index}.{ext}"

    def get_organized_path(self, idol: IdolProfile, media_item: MediaItem, index: int = 1) -> Path:
        """
        Calculate organized path:
        If custom download_dir is set:
        {base_dir}/{platform}/{photos|videos}/{YYYY-MM}/{filename}
        Otherwise:
        {base_dir}/{group}/{idol_name}/{platform}/{photos|videos}/{YYYY-MM}/{filename}
        """
        platform_dir = media_item.platform.lower()

        # Determine photos or videos subfolder
        from ..db.models import MediaType
        type_dir = "videos" if media_item.media_type == MediaType.VIDEO else "photos"
        
        # Date subfolder (YYYY-MM)
        date_str = "unknown"
        if media_item.created_at:
            try:
                date_str = media_item.created_at[:7]  # YYYY-MM
                import re
                if not re.match(r'^\d{4}-\d{2}$', date_str):
                    date_str = "unknown"
            except (AttributeError, IndexError) as e:
                logger.debug("Failed to parse date from {}: {}", media_item.created_at, e)

        filename = self.generate_filename(media_item, index)

        if idol.download_dir:
            # Custom folder: Save files flat directly inside the custom folder (no subfolders)
            return self.base_dir / filename
        else:
            # Global folder: Nest under group and idol name to prevent mixing
            group_dir = "Solo"
            if idol.group_name:
                group_dir = sanitize_filename(idol.group_name)
                flag = "🇯🇵 " if idol.idol_type == IdolType.JAPANESE else "🇰🇷 "
                group_dir = f"{flag}{group_dir}"
            else:
                flag = "🇯🇵 " if idol.idol_type == IdolType.JAPANESE else "🇰🇷 "
                group_dir = f"{flag}Solo"

            idol_dir = sanitize_filename(idol.display_name)
            return self.base_dir / group_dir / idol_dir / platform_dir / type_dir / date_str / filename

    def move_to_organized(self, temp_path: Path | str, target_path: Path | str) -> Path:
        """Move temp file to its final organized location, creating folders if needed."""
        tp = Path(temp_path)
        tgt = Path(target_path)
        
        ensure_dir(tgt.parent)
        
        # Move or copy
        shutil.move(str(tp), str(tgt))
        logger.debug("Organized file saved to: {}", tgt)
        return tgt

    def reorganize_existing_files(self) -> Dict[str, Any]:
        """Scan the download directory and move existing files to the new structured paths (splitting photos & videos)."""
        moved_paths = []
        deleted_empty_dirs = 0
        
        # Supported platforms list
        platforms = {"twitter", "weibo", "instagram", "threads", "tiktok"}
        
        # Scan recursively
        for path in list(self.base_dir.rglob("*")):
            if not path.is_file():
                continue
                
            # Skip metadata json files and checkpoints
            if path.name.startswith("_") or path.suffix == ".json" or path.name == ".gitkeep":
                continue
                
            try:
                # File structure is: {base_dir}/{group}/{idol_name}/{platform}/{YYYY-MM}/{filename}
                # Or if already migrated: {base_dir}/{group}/{idol_name}/{platform}/{photos|videos}/{YYYY-MM}/{filename}
                parts = path.relative_to(self.base_dir).parts

                # Check if this file is in the old structure: has 5 parts after base_dir
                # e.g., ("Group", "Idol", "platform", "YYYY-MM", "filename") -> length 5
                if len(parts) == 5:
                    group, idol, platform, date_str, filename = parts
                    if platform.lower() in platforms:
                        # Determine target type
                        ext = path.suffix.lower()
                        is_video = ext in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".gif"}
                        type_dir = "videos" if is_video else "photos"

                        target_path = self.base_dir / group / idol / platform / type_dir / date_str / filename

                        # Ensure target parent exists
                        target_path.parent.mkdir(parents=True, exist_ok=True)

                        # Move file
                        shutil.move(str(path), str(target_path))
                        moved_paths.append((str(path), str(target_path)))
                        logger.debug("Migrated file from old structure to: {}", target_path)
            except (ValueError, OSError) as e:
                logger.error("Failed to move file {} during reorganization: {}", path, e)
                        
        # Clean up empty directories (bottom-up)
        for path in sorted(self.base_dir.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if path.is_dir():
                try:
                    # Check if directory is empty
                    if not any(path.iterdir()):
                        path.rmdir()
                        deleted_empty_dirs += 1
                except Exception:
                    pass
                        
        return {"moved": moved_paths, "cleaned_dirs": deleted_empty_dirs}

    def write_profile_json(self, idol: IdolProfile, target_dir: Path | str) -> None:
        """Write member metadata to _profile.json."""
        p = Path(target_dir) / "_profile.json"
        
        # Serialize IdolProfile dataclass
        data = {
            "display_name": idol.display_name,
            "idol_type": idol.idol_type.value,
            "kanji_name": idol.kanji_name,
            "generation": idol.generation,
            "team": idol.team,
            "hangul_name": idol.hangul_name,
            "stage_name": idol.stage_name,
            "real_name": idol.real_name,
            "positions": idol.positions,
            "group_name": idol.group_name,
            "sub_unit": idol.sub_unit,
            "company": idol.company,
            "fandom_name": idol.fandom_name,
            "birthday": idol.birthday,
            "debut_date": idol.debut_date,
            "graduation_date": idol.graduation_date,
            "status": idol.status.value,
            "blood_type": idol.blood_type,
            "birthplace": idol.birthplace,
            "official_color": idol.official_color,
            "official_twitter": idol.official_twitter,
            "official_instagram": idol.official_instagram,
            "official_weibo": idol.official_weibo,
            "official_tiktok": idol.official_tiktok
        }
        
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("Written idol profile metadata to {}", p)
        except Exception as e:
            logger.error("Failed to write profile metadata to {}: {}", p, e)

    def write_group_info_json(self, group_name: str, members: List[IdolProfile], target_dir: Path | str) -> None:
        """Write group info metadata to _group_info.json."""
        p = Path(target_dir) / "_group_info.json"
        
        member_list = []
        company = None
        for m in members:
            member_list.append({
                "name": m.display_name,
                "status": m.status.value,
                "debut": m.debut_date
            })
            if m.company and not company:
                company = m.company

        data = {
            "group_name": group_name,
            "company": company,
            "total_members_tracked": len(members),
            "members": member_list
        }
        
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("Written group info metadata to {}", p)
        except Exception as e:
            logger.error("Failed to write group info metadata to {}: {}", p, e)

# Import re at bottom or inside method if needed
import re
