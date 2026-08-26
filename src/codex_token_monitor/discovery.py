from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import SourceIdentity
from .privacy import irreversible_hash, normalize_path


DEFAULT_RELATIVE_ROOTS = (Path(".codex") / "sessions", Path(".codex") / "archived_sessions")


def default_log_roots(home: Path | None = None) -> list[Path]:
    base = home or Path.home()
    return [base / relative for relative in DEFAULT_RELATIVE_ROOTS]


def discover_log_roots(custom_paths: Iterable[str] = (), home: Path | None = None) -> list[Path]:
    candidates = [*default_log_roots(home), *(Path(item).expanduser() for item in custom_paths if item)]
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_path(candidate)
        if normalized not in seen:
            seen.add(normalized)
            result.append(candidate)
    return result


def identify_source(path: Path) -> SourceIdentity:
    stat = path.stat()
    normalized = normalize_path(path)
    if stat.st_ino:
        identity = irreversible_hash("file-id", stat.st_dev, stat.st_ino)
    else:
        identity = irreversible_hash("file-fallback", normalized, stat.st_ctime_ns)
    return SourceIdentity(
        path=path,
        normalized_path=normalized,
        identity=identity,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def discover_jsonl_files(roots: Iterable[Path], backfill_days: int = 0) -> list[SourceIdentity]:
    cutoff_ns = 0
    if backfill_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=backfill_days)
        cutoff_ns = int(cutoff.timestamp() * 1_000_000_000)
    files: list[SourceIdentity] = []
    identities: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = root.rglob("*.jsonl")
            for path in paths:
                try:
                    if not path.is_file():
                        continue
                    source = identify_source(path)
                    if cutoff_ns and source.mtime_ns < cutoff_ns:
                        continue
                    if source.identity in identities:
                        continue
                    identities.add(source.identity)
                    files.append(source)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue
    return sorted(files, key=lambda item: (item.mtime_ns, item.normalized_path))


def roots_status(roots: Iterable[Path]) -> list[dict[str, object]]:
    from .privacy import display_path

    result: list[dict[str, object]] = []
    for root in roots:
        try:
            available = root.is_dir() and os.access(root, os.R_OK)
        except OSError:
            available = False
        result.append({"path": display_path(root), "available": available})
    return result

