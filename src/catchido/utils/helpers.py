import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

def sanitize_filename(name: str) -> str:
    """Sanitize name to make it safe for file names."""
    # Remove invalid characters
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    # Replace spaces or multiple spaces with single space
    name = re.sub(r'\s+', " ", name)
    return name.strip()

def format_filesize(size_bytes: int) -> str:
    """Format bytes to human readable format."""
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def ensure_dir(path: Path | str) -> Path:
    """Ensure directory exists."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_file_extension(url: str) -> str:
    """Extract file extension from URL, defaulting to jpg."""
    parsed = urlparse(url)
    path = parsed.path
    ext = Path(path).suffix.lower()
    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mkv', '.webm']:
        return ext.lstrip('.')
    # If parameters exist like ?format=jpg, handle it
    query = parsed.query
    if "format=" in query:
        match = re.search(r'format=([a-zA-Z0-9]+)', query)
        if match:
            return match.group(1).lower()
    # Default
    return "jpg"

def timestamp_now() -> str:
    """Return current timestamp in ISO format."""
    return datetime.utcnow().isoformat()
