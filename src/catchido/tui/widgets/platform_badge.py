"""Platform indicator badges with per-platform colors."""

from textual.widgets import Static


# Platform color map (Rich markup color names)
PLATFORM_COLORS: dict[str, str] = {
    "twitter": "#1DA1F2",
    "instagram": "#E1306C",
    "threads": "#FFFFFF",
    "tiktok": "#00F2EA",
    "weibo": "#E6162D",
}

PLATFORM_ICONS: dict[str, str] = {
    "twitter": "\U0001d54f",    # 𝕏
    "instagram": "\u24be",       # Ⓘ
    "threads": "\u0040",         # @
    "tiktok": "\u266b",          # ♫
    "weibo": "\u5fae",           # 微
}


class PlatformBadge(Static):
    """A small colored badge showing a platform name."""

    DEFAULT_CSS = """
    PlatformBadge {
        width: auto;
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        text-style: bold;
    }
    """

    def __init__(self, platform: str, badge_id: str | None = None) -> None:
        self._platform = platform.lower()
        color = PLATFORM_COLORS.get(self._platform, "#888888")
        icon = PLATFORM_ICONS.get(self._platform, "?")
        display_name = self._platform.capitalize()
        markup = f"[{color}]{icon} {display_name}[/]"
        super().__init__(markup, id=badge_id)

    @property
    def platform(self) -> str:
        return self._platform
