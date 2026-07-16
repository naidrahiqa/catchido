from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Label, Static

class SettingsView(Container):
    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.settings_content = Static("Loading settings...")

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("[bold #ff6bcb]Application Settings[/bold #ff6bcb]", classes="section-title"),
            self.settings_content,
            id="settings-container"
        )

    def on_mount(self) -> None:
        self.refresh_settings_view()

    def refresh_settings_view(self) -> None:
        c = self.config
        lines = [
            "[bold #9b59b6]General Config[/bold #9b59b6]",
            f" - [bold #ff6bcb]Download Directory:[/] {c.general.download_dir}",
            f" - [bold #ff6bcb]Max Concurrent Downloads:[/] {c.general.max_concurrent_downloads}",
            f" - [bold #ff6bcb]Auto Deduplication:[/] {c.general.auto_dedup}",
            f" - [bold #ff6bcb]Deduplication Threshold:[/] {c.general.dedup_threshold} (Hamming distance)",
            f" - [bold #ff6bcb]Prefer Higher Resolution:[/] {c.general.prefer_higher_res}",
            f" - [bold #ff6bcb]Download Photos:[/] {c.general.download_photos}",
            f" - [bold #ff6bcb]Download Videos:[/] {c.general.download_videos}",
            f" - [bold #ff6bcb]Log Level:[/] {c.general.log_level}",
            f" - [bold #ff6bcb]Log File:[/] {c.general.log_file}",
            "",
            "[bold #9b59b6]API Credentials & Sessions[/bold #9b59b6]",
            f" - [bold #ff6bcb]Twitter Bearer Token:[/] {'[green]Configured[/green]' if c.twitter.bearer_token else '[red]Missing[/red]'}",
            f" - [bold #ff6bcb]Weibo Session Cookie:[/] {'[green]Configured[/green]' if c.weibo.cookie else '[yellow]Not set[/yellow]'}",
            f" - [bold #ff6bcb]Instagram Session Cookie:[/] {'[green]Configured[/green]' if c.instagram.session_cookie else '[yellow]Not set[/yellow]'}",
            f" - [bold #ff6bcb]Threads Session Cookie:[/] {'[green]Configured[/green]' if c.threads.session_cookie else '[yellow]Not set[/yellow]'}",
            f" - [bold #ff6bcb]TikTok Session Cookie:[/] {'[green]Configured[/green]' if c.tiktok.session_cookie else '[yellow]Not set[/yellow]'}",
            "",
            "[bold #9b59b6]Search Settings[/bold #9b59b6]",
            f" - [bold #ff6bcb]Min Relevance Score:[/] {c.search.min_relevance_score}",
            f" - [bold #ff6bcb]Auto Discover Accounts:[/] {c.search.auto_discover_accounts}",
            f" - [bold #ff6bcb]Auto Generate Keywords:[/] {c.search.auto_generate_keywords}",
            f" - [bold #ff6bcb]Include Fan Content:[/] {c.search.include_fan_content}",
            f" - [bold #ff6bcb]Exclude Fanart:[/] {c.search.exclude_fanart}",
            "",
            "[bold #a89cb5]* To edit these parameters, please modify your local config.toml directly.[/bold #a89cb5]"
        ]
        self.settings_content.update("\n".join(lines))
