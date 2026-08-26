from __future__ import annotations

from datetime import datetime, timezone

from codex_token_monitor.models import ParserState
from codex_token_monitor.parser import CodexEventParser

from conftest import session, token, turn, usage


def parser() -> CodexEventParser:
    return CodexEventParser(datetime(2026, 8, 24, tzinfo=timezone.utc), source_instance="fixture")


def test_actual_confirmed_token_count_shape_and_model_context():
    item = parser()
    item.parse_object(session())
    item.parse_object(turn("gpt-5.6-sol"))
    outcome = item.parse_object(token())
    assert outcome.event is not None
    assert outcome.event.model == "gpt-5.6-sol"
    assert outcome.event.usage.as_tuple() == (10, 4, 3, 1, 14)
    assert outcome.event.usage_source == "last"


def test_missing_fields_and_unknown_schema_are_skipped():
    item = parser()
    assert item.parse_object({"type": "event_msg", "payload": {"type": "token_count"}}).diagnostic_code == "token_missing_info"
    assert item.parse_object({"type": "future", "payload": {"secret": "must-not-persist"}}).event is None
    assert item.parse_bytes(b"not-json").diagnostic_code == "invalid_json"
    assert item.parse_bytes(b"\xff\n").diagnostic_code == "invalid_utf8"


def test_sensitive_text_never_enters_parsed_record():
    secret = "SENSITIVE_PROMPT_SHOULD_NOT_APPEAR"
    item = parser()
    item.parse_object(session())
    item.parse_object(turn())
    record = token()
    record["payload"]["message"] = secret
    record["payload"]["tool_output"] = secret
    outcome = item.parse_object(record)
    assert outcome.event is not None
    assert secret not in repr(outcome.event)
    assert "synthetic-session" not in repr(outcome.event)
    assert "synthetic-turn" not in repr(outcome.event)


def test_duplicate_last_snapshot_produces_same_key():
    item = parser()
    item.parse_object(session())
    item.parse_object(turn())
    first = item.parse_object(token(timestamp="2026-08-24T10:00:02Z")).event
    second = item.parse_object(token(timestamp="2026-08-24T10:00:03Z")).event
    assert first and second and first.event_key == second.event_key


def test_total_only_uses_increase_and_handles_reset():
    item = parser()
    item.parse_object(session())
    item.parse_object(turn())
    baseline = item.parse_object(token(total=usage(100, 40, 30, 10, 140), include_last=False))
    assert baseline.event is None and baseline.diagnostic_code == "total_baseline"
    increased = item.parse_object(token(total=usage(112, 45, 35, 12, 157), include_last=False))
    assert increased.event and increased.event.usage.as_tuple() == (12, 5, 5, 2, 17)
    reset = item.parse_object(token(total=usage(0, 0, 0, 0, 0), include_last=False))
    assert reset.event is None
    after_reset = item.parse_object(token(total=usage(2, 1, 1, 0, 3), include_last=False))
    assert after_reset.event and after_reset.event.usage.as_tuple() == (2, 1, 1, 0, 3)


def test_model_switch_and_unknown_model_are_preserved():
    item = parser()
    item.parse_object(session())
    item.parse_object(turn("gpt-5.6-terra", "turn-1"))
    terra = item.parse_object(token(total=usage())).event
    item.parse_object(turn("future-model-x", "turn-2"))
    future = item.parse_object(token(total=usage(20, 8, 6, 2, 28))).event
    item.parse_object({"type": "turn_context", "payload": {"turn_id": "turn-3"}})
    unknown = item.parse_object(token(total=usage(30, 12, 9, 3, 42))).event
    assert [terra.model, future.model, unknown.model] == ["gpt-5.6-terra", "future-model-x", "unknown"]


def test_kst_date_boundary_and_timestamp_fallback():
    item = parser()
    item.parse_object(session())
    item.parse_object(turn())
    before = item.parse_object(token(timestamp="2026-08-24T14:59:59Z")).event
    after = item.parse_object(token(total=usage(20, 8, 6, 2, 28), timestamp="2026-08-24T15:00:00Z")).event
    assert before.local_date == "2026-08-24"
    assert after.local_date == "2026-08-25"
    missing = token(total=usage(30, 12, 9, 3, 42))
    missing.pop("timestamp")
    fallback = item.parse_object(missing)
    assert fallback.event and fallback.event.timestamp_fallback
    assert fallback.diagnostic_code == "timestamp_fallback"


def test_cache_and_reasoning_are_not_added_to_total():
    item = parser()
    item.parse_object(session())
    item.parse_object(turn())
    event = item.parse_object(token(last=usage(100, 50, 80, 30, 150), total=usage(100, 50, 80, 30, 150))).event
    assert event.usage.total_tokens == 150

