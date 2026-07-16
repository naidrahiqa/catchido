from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import DataTable, Input, Static, Label
from loguru import logger
from ...db import Database

class IdolListView(Container):
    def __init__(self, db_path, on_select_idol, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.on_select_idol = on_select_idol
        self.search_input = Input(placeholder="🔍 Search idols by name, group, or company...")
        self.table = DataTable()
        self.all_idols_data = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("[bold #ff6bcb]Tracked Idols & Bias Catalog[/bold #ff6bcb]", classes="section-title"),
            self.search_input,
            self.table,
            id="idol-list-container"
        )

    async def on_mount(self) -> None:
        self.table.cursor_type = "row"
        self.table.add_columns("Name", "Type", "Group", "Company", "Status", "Media Count")
        await self.refresh_list()

    async def refresh_list(self) -> None:
        try:
            async with Database(self.db_path) as db:
                idols = await db.list_idols()
                self.all_idols_data = []
                for idol in idols:
                    media_count = await db.get_media_count(idol.display_name)
                    self.all_idols_data.append({
                        "name": idol.display_name,
                        "type": idol.idol_type.value.upper(),
                        "group": idol.group_name or "-",
                        "company": idol.company or "-",
                        "status": idol.status.value,
                        "media_count": str(media_count)
                    })
            self.filter_and_render_table("")
        except Exception as e:
            logger.error("Failed to load idols table: {}", e)

    def filter_and_render_table(self, query: str) -> None:
        self.table.clear()
        query = query.lower().strip()
        for idx, row in enumerate(self.all_idols_data):
            match = (
                not query
                or query in row["name"].lower()
                or query in row["group"].lower()
                or query in row["company"].lower()
                or query in row["status"].lower()
            )
            if match:
                self.table.add_row(
                    row["name"],
                    row["type"],
                    row["group"],
                    row["company"],
                    row["status"],
                    row["media_count"],
                    key=row["name"] # Row key is display name
                )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input == self.search_input:
            self.filter_and_render_table(event.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Row key is the name of the idol
        idol_name = event.row_key.value
        self.on_select_idol(idol_name)
