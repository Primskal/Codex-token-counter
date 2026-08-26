from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_token_monitor.repository import Repository


def usage(input_tokens=10, output_tokens=4, cached_input_tokens=3, reasoning_output_tokens=1, total_tokens=14):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
        "cache_write_input_tokens": 0,
    }


def session(session_id="synthetic-session"):
    return {
        "timestamp": "2026-08-24T10:00:00.000Z",
        "type": "session_meta",
        "payload": {"id": session_id, "session_id": session_id, "source": "test"},
    }


def turn(model="gpt-5.6-sol", turn_id="synthetic-turn"):
    return {
        "timestamp": "2026-08-24T10:00:01.000Z",
        "type": "turn_context",
        "payload": {"turn_id": turn_id, "model": model},
    }


def token(last=None, total=None, timestamp="2026-08-24T10:00:02.000Z", include_last=True):
    info = {"total_token_usage": total or usage(), "model_context_window": 200000}
    if include_last:
        info["last_token_usage"] = last or usage()
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info, "rate_limits": None},
    }


def write_jsonl(path: Path, records, final_newline=True):
    content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    if final_newline:
        content += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "data" / "monitor.db")

