from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


_HASH_DOMAIN = b"codex-token-monitor-v1\0"


def irreversible_hash(*parts: object) -> str:
    digest = hashlib.sha256(_HASH_DOMAIN)
    for part in parts:
        encoded = str(part).encode("utf-8", "surrogatepass")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def canonical_numeric_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def normalize_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def display_path(path: Path) -> str:
    """Redact the home directory while retaining a useful status path."""
    try:
        home = Path.home().resolve()
        resolved = path.resolve()
        relative = resolved.relative_to(home)
        return str(Path("%USERPROFILE%") / relative)
    except (OSError, ValueError):
        return path.name or "(경로)"

