from __future__ import annotations

import csv
import io
import json
import mimetypes
import secrets
import threading
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .monitor import MonitorService
from .parser import KST
from .repository import Repository
from .settings import AutostartManager, validate_settings


DIAGNOSTIC_LABELS = {
    "invalid_utf8": "UTF-8 해석 실패",
    "invalid_json": "JSON 해석 실패",
    "unsupported_record": "지원하지 않는 레코드",
    "token_missing_info": "토큰 정보 누락",
    "token_missing_usage": "토큰 사용량 누락",
    "timestamp_fallback": "파일 수정 시각 대체 사용",
    "total_baseline": "누적 카운터 기준선 설정",
    "total_counter_reset": "누적 카운터 초기화",
    "file_truncated": "파일 축소 후 재스캔",
    "file_replaced": "파일 교체 후 재스캔",
    "file_moved": "파일 이동 감지",
    "source_temporarily_unavailable": "파일 일시 접근 불가",
    "watch_schedule_failed": "파일 감시 등록 실패",
    "reconcile_failed": "재조정 스캔 실패",
}


def _validate_date(value: str | None, fallback: date) -> str:
    if not value:
        return fallback.isoformat()
    parsed = date.fromisoformat(value)
    if parsed.year < 2000 or parsed.year > 9999:
        raise ValueError("날짜 범위가 잘못되었습니다.")
    return parsed.isoformat()


def create_csv(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["날짜", "모델", "입력", "출력", "캐시 입력", "추론 출력", "전체 토큰"])
    for row in rows:
        writer.writerow(
            [
                row["date"],
                row["model"],
                row["input_tokens"],
                row["output_tokens"],
                row["cached_input_tokens"],
                row["reasoning_output_tokens"],
                row["total_tokens"],
            ]
        )
    return stream.getvalue().encode("utf-8-sig")


class DashboardServer:
    def __init__(
        self,
        repository: Repository,
        monitor: MonitorService,
        autostart: AutostartManager,
        port: int = 8765,
    ) -> None:
        self.repository = repository
        self.monitor = monitor
        self.autostart = autostart
        self.csrf_token = secrets.token_urlsafe(32)
        self.port = port
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        if self.httpd:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"CodexTokenMonitor/{__version__}"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _secure_headers(self, content_type: str, length: int) -> None:
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                )

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self._secure_headers(content_type, len(body))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, payload: object, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._send(status, body, "application/json; charset=utf-8")

            def _allowed_host(self) -> bool:
                host = self.headers.get("Host", "").split(":", 1)[0].lower()
                return host in {"127.0.0.1", "localhost"}

            def _dates(self, query: dict[str, list[str]]) -> tuple[str, str]:
                today = datetime.now(timezone.utc).astimezone(KST).date()
                start = _validate_date(query.get("start", [None])[0], today)
                end = _validate_date(query.get("end", [None])[0], today)
                if start > end:
                    raise ValueError("시작일이 종료일보다 늦습니다.")
                return start, end

            def do_GET(self) -> None:  # noqa: N802
                if not self._allowed_host():
                    self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
                    return
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                try:
                    if parsed.path == "/":
                        template = (files("codex_token_monitor") / "web" / "dashboard.html").read_text("utf-8")
                        body = template.replace("__CSRF_TOKEN__", owner.csrf_token).encode("utf-8")
                        self._send(200, body, "text/html; charset=utf-8")
                    elif parsed.path in {"/dashboard.css", "/dashboard-layout.css", "/format.js", "/dashboard.js"}:
                        name = parsed.path.lstrip("/")
                        body = (files("codex_token_monitor") / "web" / name).read_bytes()
                        self._send(200, body, mimetypes.guess_type(name)[0] + "; charset=utf-8")
                    elif parsed.path == "/api/stats":
                        start, end = self._dates(query)
                        model = query.get("model", [None])[0]
                        granularity = query.get("granularity", ["day"])[0]
                        payload = owner.repository.query_totals(start, end)
                        payload["trend"] = owner.repository.query_trend(start, end, granularity)
                        if model:
                            payload["rows"] = owner.repository.query_daily(start, end, model)
                        self._json(payload)
                    elif parsed.path == "/api/status":
                        status = owner.monitor.status()
                        for diagnostic in status["diagnostics"]:  # type: ignore[index]
                            diagnostic["label"] = DIAGNOSTIC_LABELS.get(
                                str(diagnostic["code"]), "기타 진단"
                            )
                        self._json(status)
                    elif parsed.path == "/api/settings":
                        settings = owner.repository.all_settings()
                        settings.pop("autostart_managed_command", None)
                        settings.setdefault("custom_log_paths", [])
                        settings.setdefault("backfill_days", 0)
                        settings.setdefault("scan_interval_seconds", 15)
                        settings["autostart_enabled"] = owner.autostart.enabled()
                        self._json(settings)
                    elif parsed.path == "/api/csv":
                        start, end = self._dates(query)
                        body = create_csv(owner.repository.query_daily(start, end))
                        self.send_response(200)
                        self._secure_headers("text/csv; charset=utf-8", len(body))
                        self.send_header(
                            "Content-Disposition", f'attachment; filename="codex-token-{start}-{end}.csv"'
                        )
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        self._send(404, b"Not Found", "text/plain")
                except (ValueError, OSError) as error:
                    self._json({"error": str(error)}, 400)

            def do_POST(self) -> None:  # noqa: N802
                if not self._allowed_host() or not secrets.compare_digest(
                    self.headers.get("X-CSRF-Token", ""), owner.csrf_token
                ):
                    self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 128 * 1024)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("요청 형식이 잘못되었습니다.")
                    parsed = urlparse(self.path)
                    if parsed.path == "/api/rescan":
                        owner.monitor.request_rescan()
                    elif parsed.path == "/api/pause":
                        owner.monitor.pause()
                    elif parsed.path == "/api/resume":
                        owner.monitor.resume()
                    elif parsed.path == "/api/diagnostics/reset":
                        owner.repository.reset_diagnostics()
                    elif parsed.path == "/api/settings":
                        clean = validate_settings(payload)
                        for key in ("custom_log_paths", "backfill_days", "scan_interval_seconds"):
                            if key in clean:
                                owner.repository.set_setting(key, clean[key])
                        if "autostart_enabled" in clean:
                            owner.autostart.set_enabled(bool(clean["autostart_enabled"]))
                        owner.monitor.restart_observer()
                        owner.monitor.request_rescan()
                    else:
                        self._send(404, b"Not Found", "text/plain")
                        return
                    self._json({"ok": True})
                except (ValueError, json.JSONDecodeError, OSError) as error:
                    self._json({"error": str(error)}, 400)

        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="dashboard", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        server = self.httpd
        self.httpd = None
        if server:
            server.shutdown()
            server.server_close()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
