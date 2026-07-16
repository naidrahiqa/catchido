from textual.widgets import Static

class StatsCard(Static):
    def __init__(self, title: str, value: str, classes: str = ""):
        super().__init__(classes=f"stats-card {classes}")
        self.title = title
        self.value = value

    def render(self) -> str:
        return f"[bold #a89cb5]{self.title}[/]\n\n[bold #ff6bcb]{self.value}[/]"
