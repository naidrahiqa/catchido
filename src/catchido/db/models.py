from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

class IdolType(Enum):
    JAPANESE = "jp"
    KOREAN = "kr"

class IdolStatus(Enum):
    ACTIVE = "active"
    GRADUATED = "graduated"
    HIATUS = "hiatus"
    DISBANDED = "disbanded"
    SOLO = "solo"
    LEFT = "left"

class MediaSourceType(Enum):
    OFFICIAL = "official"
    FANSITE = "fansite"
    FAN_TAKEN = "fan_taken"
    FANCAM = "fancam"
    PRESS = "press"
    PREVIEW = "preview"
    AIRPORT = "airport"
    UNKNOWN = "unknown"

class MediaType(Enum):
    IMAGE = "image"
    VIDEO = "video"

@dataclass
class IdolProfile:
    display_name: str
    idol_type: IdolType
    
    # JP Specific
    kanji_name: Optional[str] = None
    generation: Optional[str] = None
    team: Optional[str] = None
    
    # KR Specific
    hangul_name: Optional[str] = None
    stage_name: Optional[str] = None
    real_name: Optional[str] = None
    positions: List[str] = field(default_factory=list)
    
    # Group Info
    group_name: Optional[str] = None
    sub_unit: Optional[str] = None
    company: Optional[str] = None
    fandom_name: Optional[str] = None
    
    # Personal Info
    birthday: Optional[str] = None
    debut_date: Optional[str] = None
    graduation_date: Optional[str] = None
    status: IdolStatus = IdolStatus.ACTIVE
    download_dir: Optional[str] = None
    
    # Metadata
    blood_type: Optional[str] = None
    birthplace: Optional[str] = None
    official_color: Optional[str] = None
    
    # Official Accounts
    official_twitter: Optional[str] = None
    official_instagram: Optional[str] = None
    official_weibo: Optional[str] = None
    official_tiktok: Optional[str] = None
    
    # Timestamps
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@dataclass
class IdolKeywordEntry:
    idol_name: str
    idol_type: IdolType
    keyword: str
    script_type: Optional[str] = None  # 'kanji', 'hiragana', etc.
    platform: str = "all"              # 'twitter', 'weibo', 'threads', 'all'
    is_auto_generated: bool = False
    is_active: bool = True
    hit_count: int = 0
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None

@dataclass
class TrustedAccount:
    idol_name: str
    platform: str
    username: str
    account_type: str = "fansite"       # 'official', 'fansite', 'fan', 'press', 'homma'
    is_auto_discovered: bool = False
    media_count: int = 0
    created_at: Optional[str] = None

@dataclass
class MediaHash:
    file_path: str
    sha256: str
    phash: Optional[str] = None
    dhash: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: Optional[int] = None
    source_url: Optional[str] = None
    source_platform: Optional[str] = None
    source_user: Optional[str] = None
    idol_name: Optional[str] = None
    downloaded_at: Optional[str] = None

@dataclass
class MediaItem:
    url: str
    platform: str
    post_id: str
    author: str
    media_type: MediaType
    width: Optional[int] = None
    height: Optional[int] = None
    original_url: Optional[str] = None
    created_at: Optional[str] = None
    text: str = ""
    hashtags: List[str] = field(default_factory=list)

@dataclass
class DownloadCheckpoint:
    idol_name: str
    platform: str
    source_username: str
    last_id: str
    last_checked_at: Optional[str] = None

@dataclass
class DedupResult:
    is_duplicate: bool
    is_near_duplicate: bool
    existing_path: Optional[str] = None
    should_replace: bool = False
    reason: str = ""
