from __future__ import annotations

import copy
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .discovery import discover_jsonl_files, discover_log_roots, roots_status
from .models import Checkpoint, ParserState, ScanResult, SourceIdentity, TurnModelHint
from .parser import CodexEventParser, PARSER_SCHEMA_VERSION
from .reader import checkpoint_line_matches, iter_complete_lines
from .repository import Repository


@dataclass(slots=True)
class MonitorStatus:
    state: str = "시작 중"
    paused: bool = False
    backfill_complete: bool = False
    backfill_current: int = 0
    backfill_total: int = 0
    last_sync_utc: str | None = None
    last_processed_utc: str | None = None
    files_discovered: int = 0
    files_scanned: int = 0
    inserted_events_session: int = 0
    duplicate_events_session: int = 0
    skipped_events_session: int = 0
    last_error_code: str | None = None
    tray_ready: bool = False
    roots: list[dict[str, object]] = field(default_factory=list)


class _LogHintHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:
        paths = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
        if any(str(path).lower().endswith(".jsonl") for path in paths):
            self.callback()


class MonitorService:
    def __init__(
        self,
        repository: Repository,
        batch_lines: int = 1000,
        roots_override: list[Path] | None = None,
    ) -> None:
        self.repository = repository
        self.batch_lines = batch_lines
        self._status = MonitorStatus()
        self._status_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._rescan_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer: Observer | None = None
        self._roots_override = roots_override

    def _settings(self) -> tuple[list[Path], int, float]:
        interval = self.repository.get_setting("scan_interval_seconds", 15)
        try:
            interval = max(2.0, min(3600.0, float(interval)))
        except (TypeError, ValueError):
            interval = 15.0
        roots = self._roots_override if self._roots_override is not None else discover_log_roots()
        return roots, 0, interval

    def status(self) -> dict[str, object]:
        with self._status_lock:
            value = asdict(self._status)
        value["processed_events"] = self.repository.event_count()
        value["diagnostics"] = self.repository.diagnostics()
        return value

    def _update_status(self, **values: object) -> None:
        with self._status_lock:
            for key, value in values.items():
                setattr(self._status, key, value)

    def set_tray_ready(self, ready: bool) -> None:
        self._update_status(tray_ready=ready)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._rescan_event.set()
        self._start_observer()
        self._thread = threading.Thread(target=self._run, name="codex-log-monitor", daemon=True)
        self._thread.start()

    def _start_observer(self) -> None:
        roots, _, _ = self._settings()
        observer = Observer()
        scheduled = 0
        handler = _LogHintHandler(self.request_rescan)
        for root in roots:
            if root.is_dir():
                try:
                    observer.schedule(handler, str(root), recursive=True)
                    scheduled += 1
                except OSError:
                    self.repository.increment_diagnostic("watch_schedule_failed")
        if scheduled:
            observer.start()
            self._observer = observer

    def restart_observer(self) -> None:
        observer = self._observer
        self._observer = None
        if observer:
            observer.stop()
            observer.join(timeout=5)
        self._start_observer()

    def request_rescan(self) -> None:
        self._rescan_event.set()

    def pause(self) -> None:
        self._update_status(paused=True, state="일시중지")

    def resume(self) -> None:
        self._update_status(paused=False, state="감시 중")
        self.request_rescan()

    def stop(self) -> None:
        self._stop_event.set()
        self._rescan_event.set()
        observer = self._observer
        self._observer = None
        if observer:
            observer.stop()
            observer.join(timeout=5)
        if self._thread:
            self._thread.join(timeout=15)
        self._update_status(state="종료됨")

    def _run(self) -> None:
        first = True
        while not self._stop_event.is_set():
            with self._status_lock:
                paused = self._status.paused
            if not paused:
                try:
                    self.run_once(is_backfill=first)
                    first = False
                except Exception:
                    self.repository.increment_diagnostic("reconcile_failed")
                    self._update_status(state="오류 후 재시도", last_error_code="reconcile_failed")
            _, _, interval = self._settings()
            self._rescan_event.clear()
            self._rescan_event.wait(interval)

    def run_once(self, is_backfill: bool = False) -> ScanResult:
        roots, backfill_days, _ = self._settings()
        self._update_status(state="백필 중" if is_backfill else "재조정 중", roots=roots_status(roots))
        sources = discover_jsonl_files(roots, backfill_days)
        self._update_status(
            backfill_current=0,
            backfill_total=len(sources),
            files_discovered=len(sources),
        )
        combined = ScanResult(files_discovered=len(sources))
        for index, source in enumerate(sources, start=1):
            if self._stop_event.is_set():
                break
            with self._status_lock:
                if self._status.paused:
                    break
            try:
                result = self.scan_source(source)
            except (OSError, PermissionError):
                self.repository.increment_diagnostic("source_temporarily_unavailable")
                combined.skipped_events += 1
                continue
            combined.files_scanned += result.files_scanned
            combined.complete_lines += result.complete_lines
            combined.inserted_events += result.inserted_events
            combined.duplicate_events += result.duplicate_events
            combined.skipped_events += result.skipped_events
            combined.bytes_processed += result.bytes_processed
            self._update_status(backfill_current=index)
        now = datetime.now(timezone.utc).isoformat()
        self._update_status(
            state="감시 중" if not self._status.paused else "일시중지",
            backfill_complete=not self._stop_event.is_set(),
            last_sync_utc=now,
            files_scanned=combined.files_scanned,
            inserted_events_session=self._status.inserted_events_session + combined.inserted_events,
            duplicate_events_session=self._status.duplicate_events_session + combined.duplicate_events,
            skipped_events_session=self._status.skipped_events_session + combined.skipped_events,
            last_processed_utc=now if combined.complete_lines else self._status.last_processed_utc,
        )
        return combined

    def scan_source(self, source: SourceIdentity) -> ScanResult:
        result = ScanResult(files_discovered=1, files_scanned=1)
        checkpoint = self.repository.get_checkpoint(source.identity)
        reset_code: str | None = None
        if checkpoint is None:
            previous_at_path = self.repository.get_checkpoint_by_path(source.normalized_path)
            if previous_at_path is not None and previous_at_path.source_identity != source.identity:
                self.repository.increment_diagnostic("file_replaced")
            checkpoint = Checkpoint(source_identity=source.identity, normalized_path=source.normalized_path)
        elif checkpoint.parser_version != PARSER_SCHEMA_VERSION:
            reset_code = "parser_version_rescan"
        elif source.size < checkpoint.byte_offset:
            reset_code = "file_truncated"
        elif checkpoint.byte_offset and not checkpoint_line_matches(
            source.path, checkpoint.last_line_start, checkpoint.byte_offset, checkpoint.last_line_hash
        ):
            reset_code = "file_replaced"
        if reset_code:
            self.repository.increment_diagnostic(reset_code)
            checkpoint.byte_offset = 0
            checkpoint.last_line_start = 0
            checkpoint.last_line_hash = ""
            checkpoint.parser_state = ParserState()
        elif checkpoint.normalized_path != source.normalized_path:
            self.repository.increment_diagnostic("file_moved")

        checkpoint.normalized_path = source.normalized_path
        checkpoint.file_size = source.size
        checkpoint.mtime_ns = source.mtime_ns
        checkpoint.parser_version = PARSER_SCHEMA_VERSION
        fallback_time = datetime.fromtimestamp(source.mtime_ns / 1_000_000_000, timezone.utc)
        parser = CodexEventParser(
            fallback_time,
            copy.deepcopy(checkpoint.parser_state),
            source_instance=source.identity,
        )
        batch_events: list[tuple[object, int]] = []
        batch_model_hints: list[TurnModelHint] = []
        batch_diagnostics: Counter[str] = Counter()
        batch_count = 0
        last_end = checkpoint.byte_offset
        last_start = checkpoint.last_line_start
        last_hash = checkpoint.last_line_hash

        def commit_batch() -> None:
            nonlocal batch_events, batch_model_hints, batch_diagnostics, batch_count
            checkpoint.byte_offset = last_end
            checkpoint.last_line_start = last_start
            checkpoint.last_line_hash = last_hash
            checkpoint.parser_state = copy.deepcopy(parser.state)
            inserted, duplicates = self.repository.apply_batch(
                checkpoint,
                batch_events,  # type: ignore[arg-type]
                batch_diagnostics,
                batch_model_hints,
            )
            result.inserted_events += inserted
            result.duplicate_events += duplicates
            batch_events = []
            batch_model_hints = []
            batch_diagnostics = Counter()
            batch_count = 0

        for line in iter_complete_lines(source.path, checkpoint.byte_offset):
            outcome = parser.parse_bytes(line.raw)
            result.complete_lines += 1
            result.bytes_processed += line.end - line.start
            if outcome.event is not None:
                batch_events.append((outcome.event, line.start))
            if outcome.model_hint is not None:
                batch_model_hints.append(outcome.model_hint)
            if outcome.diagnostic_code:
                batch_diagnostics[outcome.diagnostic_code] += 1
                if outcome.event is None:
                    result.skipped_events += 1
            last_end = line.end
            last_start = line.start
            last_hash = line.digest
            batch_count += 1
            if batch_count >= self.batch_lines:
                commit_batch()
                if self._stop_event.is_set():
                    break
        if batch_count:
            commit_batch()
        else:
            checkpoint.parser_state = copy.deepcopy(parser.state)
            self.repository.apply_batch(checkpoint, [])
        return result
