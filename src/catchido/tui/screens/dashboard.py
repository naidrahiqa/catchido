from textual.app import ComposeResult
from textual.containers import Container, Grid
from textual.widgets import Static
from ...db import Database
from ...utils.helpers import format_filesize
from ..widgets.stats_panel import StatsCard

class DashboardView(Container):
    def __init__(self, db_path, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        
        # Create stats cards placeholder
        self.total_idols_card = StatsCard("Total Tracked Idols", "0")
        self.total_files_card = StatsCard("Total Downloaded Media", "0")
        self.total_size_card = StatsCard("Total Storage Usage", "0.00 B")
        self.activity_log = Static("[bold #ff6bcb]Recent Activity[/bold #ff6bcb]\n\nCatchido TUI is active. Press 'd' to download or select options from the sidebar.", id="activity-log-content")

    def compose(self) -> ComposeResult:
        yield Grid(
            self.total_idols_card,
            self.total_files_card,
            self.total_size_card,
            classes="dashboard-grid"
        )
        yield Container(
            self.activity_log,
            classes="recent-activity-panel"
        )

    async def refresh_stats(self) -> None:
        try:
            async with Database(self.db_path) as db:
                idols = await db.list_idols()
                stats_data = await db.get_download_stats()
                
            self.total_idols_card.value = str(len(idols))
            self.total_files_card.value = str(stats_data.get("total_count", 0))
            self.total_size_card.value = format_filesize(stats_data.get("total_size", 0))
            
            # Re-render the cards
            self.total_idols_card.refresh()
            self.total_files_card.refresh()
            self.total_size_card.refresh()
            
            # Refresh activity text
            platform_summaries = []
            for plat, details in stats_data.get("platforms", {}).items():
                size_str = format_filesize(details.get("size", 0))
                platform_summaries.append(f" - [bold #9b59b6]{plat.capitalize()}[/]: {details.get('count', 0)} files ({size_str})")
            
            platform_text = "\n".join(platform_summaries) if platform_summaries else " No downloaded media yet."
            self.activity_log.update(
                "[bold #ff6bcb]Platform Breakdown[/bold #ff6bcb]\n\n"
                f"{platform_text}\n\n"
                "[bold #ff6bcb]Quick Actions[/bold #ff6bcb]\n"
                " - Switch tabs in sidebar or press keys: [bold #ff6bcb]d[/] (Download), [bold #ff6bcb]i[/] (Idols), [bold #ff6bcb]s[/] (Settings)"
            )
        except Exception as e:
            self.activity_log.update(f"[red]Error loading dashboard stats: {e}[/red]")
