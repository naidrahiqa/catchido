from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, Button, Label
from ...db import Database

class IdolDetailView(Container):
    def __init__(self, db_path, on_back, on_start_download, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.on_back = on_back
        self.on_start_download = on_start_download
        self.idol_name = None
        
        self.profile_info_static = Static("Select an idol first.")
        self.sources_static = Static("No sources registered.")
        self.keywords_static = Static("No keywords expanded.")
        self.title_label = Label("[bold #ff6bcb]Idol Profile Details[/bold #ff6bcb]", classes="section-title")

    def compose(self) -> ComposeResult:
        yield self.title_label
        yield Horizontal(
            Button("⬅ Back to List", id="btn-back", classes="sidebar-btn"),
            Button("🚀 Scrape & Download", id="btn-scrape-this", classes="sidebar-btn primary"),
            classes="detail-actions"
        )
        yield Container(
            Container(
                Label("[bold #9b59b6]General Info[/bold #9b59b6]"),
                self.profile_info_static,
                classes="profile-section"
            ),
            Container(
                Label("[bold #9b59b6]Tracked Accounts & Keywords[/bold #9b59b6]"),
                Label("[bold #a89cb5]Sources:[/bold #a89cb5]"),
                self.sources_static,
                Label("\n[bold #a89cb5]Keywords & Tags:[/bold #a89cb5]"),
                self.keywords_static,
                classes="profile-section"
            ),
            classes="profile-container"
        )

    async def set_idol(self, name: str) -> None:
        self.idol_name = name
        self.title_label.update(f"[bold #ff6bcb]Profile: {name}[/bold #ff6bcb]")
        await self.refresh_details()

    async def refresh_details(self) -> None:
        if not self.idol_name:
            return

        try:
            async with Database(self.db_path) as db:
                idol = await db.get_idol(self.idol_name)
                if not idol:
                    self.profile_info_static.update(f"[red]Idol {self.idol_name} not found.[/red]")
                    return
                
                keywords = await db.get_keywords_for_idol(self.idol_name)
                trusted = await db.get_trusted_accounts(self.idol_name)
                media_count = await db.get_media_count(self.idol_name)

            # Profile Info
            info_lines = [
                f"[bold #ff6bcb]Display Name:[/] {idol.display_name}",
                f"[bold #ff6bcb]Type:[/] {idol.idol_type.value.upper()}",
            ]
            if idol.idol_type.value == "jp":
                info_lines.extend([
                    f"[bold #ff6bcb]Kanji Name:[/] {idol.kanji_name or '-'}",
                    f"[bold #ff6bcb]Generation:[/] {idol.generation or '-'}",
                    f"[bold #ff6bcb]Team:[/] {idol.team or '-'}",
                ])
            else:
                info_lines.extend([
                    f"[bold #ff6bcb]Hangul Name:[/] {idol.hangul_name or '-'}",
                    f"[bold #ff6bcb]Stage Name:[/] {idol.stage_name or '-'}",
                    f"[bold #ff6bcb]Real Name:[/] {idol.real_name or '-'}",
                    f"[bold #ff6bcb]Position:[/] {', '.join(idol.positions) if idol.positions else '-'}",
                ])
            info_lines.extend([
                f"[bold #ff6bcb]Group:[/] {idol.group_name or '-'}",
                f"[bold #ff6bcb]Company:[/] {idol.company or '-'}",
                f"[bold #ff6bcb]Birthday:[/] {idol.birthday or '-'}",
                f"[bold #ff6bcb]Debut Date:[/] {idol.debut_date or '-'}",
                f"[bold #ff6bcb]Status:[/] {idol.status.value}",
                f"[bold #ff6bcb]Graduation Date:[/] {idol.graduation_date or '-'}",
                f"[bold #ff6bcb]Downloaded Files:[/] {media_count}",
            ])
            self.profile_info_static.update("\n".join(info_lines))

            # Sources Info
            sources_lines = []
            for plat in ["twitter", "weibo", "instagram", "threads", "tiktok"]:
                accts = [t.username for t in trusted if t.platform == plat]
                if accts:
                    sources_lines.append(f" - [bold #9b59b6]{plat.capitalize()}:[/] {', '.join(accts)}")
            self.sources_static.update("\n".join(sources_lines) if sources_lines else "No source accounts registered.")

            # Keywords Info
            tags = [k.keyword for k in keywords if k.keyword.startswith("#")]
            terms = [k.keyword for k in keywords if not k.keyword.startswith("#")]
            
            kw_text = f"[bold #a89cb5]Search Terms:[/] {', '.join(terms[:10])}...\n"
            kw_text += f"[bold #a89cb5]Hashtags:[/] {', '.join(tags[:10])}..."
            self.keywords_static.update(kw_text)

        except Exception as e:
            self.profile_info_static.update(f"[red]Error loading details: {e}[/red]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.on_back()
        elif event.button.id == "btn-scrape-this" and self.idol_name:
            self.on_start_download(self.idol_name)
