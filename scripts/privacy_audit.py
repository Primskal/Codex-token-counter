"""Allowlist-based persistence audit. Never prints source text or identifiers."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ALLOWED_COLUMNS = {
    "file_checkpoints": {
        "source_identity", "normalized_path", "file_size", "mtime_ns", "byte_offset",
        "last_line_start", "last_line_hash", "parser_state_json", "parser_version", "updated_at_utc",
    },
    "processed_events": {
        "event_key", "event_time_utc", "source_identity", "source_offset", "parser_version", "inserted_at_utc",
    },
    "token_events": {
        "event_key", "local_date", "model", "session_hash", "turn_hash", "usage_source",
        "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens",
        "total_tokens", "timestamp_fallback",
    },
    "daily_model_aggregates": {
        "local_date", "model", "input_tokens", "output_tokens", "cached_input_tokens",
        "reasoning_output_tokens", "total_tokens", "event_count",
    },
    "diagnostic_counters": {"code", "count", "last_seen_utc"},
    "app_settings": {"key", "value", "updated_at_utc"},
}


SENSITIVE_KEYS = {
    "message", "text", "content", "input", "output", "stdout", "stderr", "instructions",
    "base_instructions", "developer_instructions", "system_instructions", "prompt", "result", "invocation",
}


def schema_audit(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table, allowed in ALLOWED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        unexpected = columns - allowed
        if unexpected:
            errors.append(f"{table}:unexpected_columns={len(unexpected)}")
    return errors


def collect_sensitive_samples(log_roots: list[Path], maximum: int = 500) -> list[bytes]:
    samples: list[bytes] = []

    def visit(value: object, key: str = "") -> None:
        if len(samples) >= maximum:
            return
        if isinstance(value, dict):
            for child_key, child in value.items():
                if str(child_key).lower() in SENSITIVE_KEYS and isinstance(child, str) and len(child) >= 16:
                    samples.append(child.encode("utf-8"))
                else:
                    visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    for root in log_roots:
        if not root.is_dir() or len(samples) >= maximum:
            continue
        for path in root.rglob("*.jsonl"):
            try:
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            visit(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                        if len(samples) >= maximum:
                            return samples
            except (OSError, UnicodeError):
                continue
    return samples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--log-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    with sqlite3.connect(args.db) as connection:
        errors = schema_audit(connection)
    targets = [args.db]
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(args.db) + suffix)
        if sidecar.exists():
            targets.append(sidecar)
    if args.csv:
        targets.append(args.csv)
    samples = collect_sensitive_samples(args.log_root)
    leak_matches = 0
    blobs = [target.read_bytes() for target in targets if target.exists()]
    for sample in samples:
        if any(sample in blob for blob in blobs):
            leak_matches += 1
    print(json.dumps({
        "schema_errors": len(errors),
        "sensitive_samples_checked": len(samples),
        "sensitive_matches": leak_matches,
        "targets_checked": len(blobs),
    }))
    return 1 if errors or leak_matches else 0


if __name__ == "__main__":
    raise SystemExit(main())
