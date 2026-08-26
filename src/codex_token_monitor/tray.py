from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from .dashboard import DashboardServer
from .monitor import MonitorService
from .parser import KST
from .repository import Repository


def create_icon_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=15, fill=(21, 34, 50, 255))
    draw.ellipse((15, 15, 49, 49), outline=(72, 210, 170, 255), width=6)
    draw.line((32, 10, 32, 20), fill=(230, 248, 243, 255), width=4)
    draw.line((44, 38, 51, 45), fill=(230, 248, 243, 255), width=4)
    return image


class TrayApplication:
    def __init__(
        self,
        repository: Repository,
        monitor: MonitorService,
        dashboard: DashboardServer,
        shutdown_callback: Callable[[], None],
    ) -> None:
        self.repository = repository
        self.monitor = monitor
        self.dashboard = dashboard
        self.shutdown_callback = shutdown_callback
        self.icon: pystray.Icon | None = None

    def _today_rows(self) -> list[dict[str, object]]:
        today = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
        return self.repository.query_daily(today, today)

    def _today_label(self, _item: object = None) -> str:
        total = sum(int(row["total_tokens"]) for row in self._today_rows())
        return f"오늘 전체: {total:,} 토큰"

    def _model_menu(self) -> pystray.Menu:
        rows = self._today_rows()
        if not rows:
            return pystray.Menu(pystray.MenuItem("기록 없음", None, enabled=False))
        return pystray.Menu(
            *(pystray.MenuItem(f"{row['model']}: {int(row['total_tokens']):,}", None, enabled=False) for row in rows)
        )

    def open_dashboard(self, *_: object) -> None:
        webbrowser.open(self.dashboard.url)

    def open_settings(self, *_: object) -> None:
        webbrowser.open(self.dashboard.url + "?settings=1")

    def toggle_pause(self, *_: object) -> None:
        if bool(self.monitor.status()["paused"]):
            self.monitor.resume()
        else:
            self.monitor.pause()
        if self.icon:
            self.icon.update_menu()

    def _pause_label(self, _item: object = None) -> str:
        return "감시 재개" if bool(self.monitor.status()["paused"]) else "감시 일시중지"

    def exit(self, *_: object) -> None:
        if self.icon:
            self.icon.stop()
        self.shutdown_callback()

    def run(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem(self._today_label, None, enabled=False),
            pystray.MenuItem("모델별 오늘 합계", pystray.Menu(self._model_menu)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("대시보드 열기", self.open_dashboard, default=True),
            pystray.MenuItem("즉시 재스캔", lambda *_: self.monitor.request_rescan()),
            pystray.MenuItem(self._pause_label, self.toggle_pause),
            pystray.MenuItem("설정", self.open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", self.exit),
        )
        self.icon = pystray.Icon(
            "CodexTokenMonitor", create_icon_image(), "Codex Token Monitor", menu
        )

        def setup(icon: pystray.Icon) -> None:
            icon.visible = True
            self.monitor.set_tray_ready(bool(icon.visible))

        try:
            self.icon.run(setup=setup)
        finally:
            self.monitor.set_tray_ready(False)
