from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path

from .dashboard import DashboardServer, create_csv
from .dpi import enable_per_monitor_dpi_awareness
from .monitor import MonitorService
from .repository import Repository
from .settings import AutostartManager
from .single_instance import SingleInstance
from .tray import TrayApplication


APP_DIR_NAME = "CodexTokenMonitor"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    return Path(base) / APP_DIR_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex 로컬 토큰 사용량 감시기")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-root", action="append", type=Path, help="검증/개발용 로그 루트 재정의")
    parser.add_argument("--once", action="store_true", help="재조정 스캔 1회 후 종료")
    parser.add_argument("--no-tray", action="store_true", help="트레이 없이 대시보드 실행")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--export", nargs=3, metavar=("START", "END", "PATH"))
    return parser


def main(argv: list[str] | None = None) -> int:
    # Packaged releases receive this mode from the PE manifest. This is a
    # harmless best-effort fallback for ``python -m`` development launches.
    enable_per_monitor_dpi_awareness()
    args = build_parser().parse_args(argv)
    repository = Repository(args.data_dir / "monitor.db")
    monitor = MonitorService(repository, roots_override=args.log_root)

    if args.export:
        start, end, output = args.export
        date.fromisoformat(start)
        date.fromisoformat(end)
        Path(output).write_bytes(create_csv(repository.query_daily(start, end)))
        return 0

    if args.once:
        result = monitor.run_once(is_backfill=True)
        print(json.dumps({
            "files_discovered": result.files_discovered,
            "files_scanned": result.files_scanned,
            "inserted_events": result.inserted_events,
            "duplicate_events": result.duplicate_events,
            "skipped_events": result.skipped_events,
            "processed_events": repository.event_count(),
        }, ensure_ascii=False))
        return 0

    instance = SingleInstance()
    if not instance.acquire():
        return 2

    stop_event = threading.Event()
    dashboard: DashboardServer | None = None

    def shutdown() -> None:
        stop_event.set()

    try:
        autostart = AutostartManager(repository)
        monitor.start()
        dashboard = DashboardServer(repository, monitor, autostart, args.port)
        dashboard.start()
        if args.no_tray:
            if not args.no_browser:
                webbrowser.open(dashboard.url)
            for name in ("SIGINT", "SIGTERM"):
                if hasattr(signal, name):
                    signal.signal(getattr(signal, name), lambda *_: stop_event.set())
            while not stop_event.wait(0.5):
                pass
        else:
            tray = TrayApplication(repository, monitor, dashboard, shutdown)
            tray.run()
        return 0
    finally:
        if dashboard:
            dashboard.stop()
        monitor.stop()
        instance.release()
