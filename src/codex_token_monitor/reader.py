from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True, slots=True)
class CompleteLine:
    start: int
    end: int
    raw: bytes
    digest: str


def line_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def iter_complete_lines(path: Path, offset: int = 0, chunk_size: int = 256 * 1024) -> Iterator[CompleteLine]:
    """Yield only newline-terminated lines, retaining a partial final line for the next scan."""
    with path.open("rb") as stream:
        stream.seek(offset)
        pending = bytearray()
        pending_start = offset
        while True:
            block = stream.read(chunk_size)
            if not block:
                return
            pending.extend(block)
            scan_from = 0
            while True:
                newline = pending.find(b"\n", scan_from)
                if newline < 0:
                    if scan_from:
                        del pending[:scan_from]
                        pending_start += scan_from
                    break
                raw = bytes(pending[scan_from:newline])
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                end = pending_start + newline + 1
                start = pending_start + scan_from
                yield CompleteLine(start=start, end=end, raw=raw, digest=line_digest(raw))
                scan_from = newline + 1


def checkpoint_line_matches(path: Path, start: int, end: int, expected_digest: str) -> bool:
    if not expected_digest or end <= start:
        return True
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            raw = stream.read(end - start)
    except OSError:
        return False
    if not raw.endswith(b"\n"):
        return False
    raw = raw[:-1]
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    return line_digest(raw) == expected_digest

