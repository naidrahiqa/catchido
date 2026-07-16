from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Button, ContentSwitcher, Label

from .screens.dashboard import DashboardView
from .screens.idol_list import IdolListView
from .screens.idol_detail import IdolDetailView
from .screens.download import DownloadView
from .screens.settings import SettingsView

class CatchidoApp(App):
    TITLE = "🎯 Catchido"
    SUB_TITLE = "Smart HD Idol Media Manager"
    CSS_PATH = "catchido.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("h", "switch_view('dashboard')", "Home/Dashboard"),
        ("i", "switch_view('idols')", "Idols List"),
        ("d", "switch_view('download')", "Download Screen"),
        ("s", "switch_view('settings')", "Settings"),
    ]

    def __init__(self, config, db_path, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.db_path = db_path
        
        # Instantiate views
        self.dashboard_view = DashboardView(self.db_path, id="dashboard")
        self.idol_list_view = IdolListView(self.db_path, on_select_idol=self.show_idol_detail, id="idols")
        self.idol_detail_view = IdolDetailView(
            self.db_path, 
            on_back=self.show_idols_list, 
            on_start_download=self.trigger_download_for_idol, 
            id="idol-detail"
        )
        self.download_view = DownloadView(self.db_path, self.config, id="download")
        self.settings_view = SettingsView(self.config, id="settings")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Label("🎯 Catchido", classes="sidebar-title"),
                Button("🏠 Dashboard", id="btn-nav-dashboard", classes="sidebar-btn"),
                Button("📋 Tracked Idols", id="btn-nav-idols", classes="sidebar-btn"),
                Button("🚀 Scrape & Download", id="btn-nav-download", classes="sidebar-btn"),
                Button("⚙ Settings", id="btn-nav-settings", classes="sidebar-btn"),
                id="sidebar"
            ),
            Container(
                ContentSwitcher(
                    self.dashboard_view,
                    self.idol_list_view,
                    self.idol_detail_view,
                    self.download_view,
                    self.settings_view,
                    initial="dashboard",
                    id="content-switcher"
                ),
                id="main-content"
            ),
            id="body"
        )
        yield Footer()

    async def on_mount(self) -> None:
        # Auto-initialize database schema if the file is new or missing tables
        from ..db import Database
        async with Database(self.db_path) as db:
            await db.initialize()
            
        self.update_active_button("dashboard")
        self.run_worker(self.dashboard_view.refresh_stats())

    def action_switch_view(self, view_id: str) -> None:
        self.switch_to_view(view_id)

    def switch_to_view(self, view_id: str) -> None:
        switcher = self.query_one("#content-switcher", ContentSwitcher)
        switcher.current = view_id
        self.update_active_button(view_id)
        
        # Refresh dynamic statistics
        if view_id == "dashboard":
            self.run_worker(self.dashboard_view.refresh_stats())
        elif view_id == "idols":
            self.run_worker(self.idol_list_view.refresh_list())
        elif view_id == "download":
            self.run_worker(self.download_view.refresh_idols_list())

    def update_active_button(self, active_view_id: str) -> None:
        # Normalize details view nav button
        button_id = active_view_id
        if active_view_id == "idol-detail":
            button_id = "idols"
            
        nav_buttons = {
            "dashboard": "#btn-nav-dashboard",
            "idols": "#btn-nav-idols",
            "download": "#btn-nav-download",
            "settings": "#btn-nav-settings",
        }
        
        for view, query in nav_buttons.items():
            btn = self.query_one(query, Button)
            if view == button_id:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-nav-dashboard":
            self.switch_to_view("dashboard")
        elif event.button.id == "btn-nav-idols":
            self.switch_to_view("idols")
        elif event.button.id == "btn-nav-download":
            self.switch_to_view("download")
        elif event.button.id == "btn-nav-settings":
            self.switch_to_view("settings")

    def show_idol_detail(self, idol_name: str) -> None:
        self.run_worker(self._load_detail_and_switch(idol_name))

    async def _load_detail_and_switch(self, idol_name: str) -> None:
        await self.idol_detail_view.set_idol(idol_name)
        self.switch_to_view("idol-detail")

    def show_idols_list(self) -> None:
        self.switch_to_view("idols")

    def trigger_download_for_idol(self, idol_name: str) -> None:
        self.switch_to_view("download")
        self.download_view.select_idol(idol_name)

def main():
    import sys
    import asyncio
    from ..config import load_config
    
    cfg = load_config()
    db_path = Path(cfg.general.download_dir) / "catchido.db"
    
    # Initialize the database schema first
    async def init_db():
        from ..db import Database
        async with Database(db_path) as db:
            await db.initialize()
            
    asyncio.run(init_db())
    
    app = CatchidoApp(config=cfg, db_path=db_path)
    app.run()

if __name__ == "__main__":
    main()
