"""Compact idol info card widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from ...db.models import IdolProfile, IdolType, IdolStatus


STATUS_STYLES: dict[str, str] = {
    "active": "[green]\u25cf Active[/]",
    "graduated": "[dim]\u25cb Graduated[/]",
    "hiatus": "[yellow]\u25cf Hiatus[/]",
    "disbanded": "[red]\u25cb Disbanded[/]",
    "solo": "[cyan]\u25cf Solo[/]",
    "left": "[dim red]\u25cb Left[/]",
}

TYPE_LABELS: dict[str, str] = {
    "jp": "[#FF6B8A]\U0001f1ef\U0001f1f5 JP[/]",
    "kr": "[#8B5CF6]\U0001f1f0\U0001f1f7 KR[/]",
}


class IdolCard(Static):
    """Compact idol info card showing name, group, type, and status."""

    DEFAULT_CSS = """
    IdolCard {
        width: 100%;
        height: auto;
        min-height: 3;
        padding: 1 2;
        margin: 0 0 1 0;
        border: round $accent;
        background: $surface;
    }

    IdolCard:hover {
        background: $surface-lighten-1;
        border: round $accent-lighten-1;
    }

    IdolCard .card-name {
        text-style: bold;
        color: $text;
    }

    IdolCard .card-meta {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        profile: IdolProfile,
        media_count: int = 0,
        card_id: str | None = None,
    ) -> None:
        super().__init__(id=card_id)
        self._profile = profile
        self._media_count = media_count

    def compose(self) -> ComposeResult:
        p = self._profile
        type_label = TYPE_LABELS.get(p.idol_type.value, p.idol_type.value)
        status_label = STATUS_STYLES.get(p.status.value, p.status.value)
        group_display = p.group_name or "Solo"

        with Vertical():
            with Horizontal():
                yield Static(
                    f"[bold]{p.display_name}[/bold]  {type_label}",
                    classes="card-name",
                )
            with Horizontal():
                yield Static(
                    f"{group_display}  {status_label}  "
                    f"[dim]{self._media_count} files[/dim]",
                    classes="card-meta",
                )
