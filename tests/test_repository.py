from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pytest

from codex_token_monitor.dashboard import create_csv
from codex_token_monitor.models import Checkpoint, ParsedTokenEvent, TokenUsage, TurnModelHint


def make_event(key="e1", day="2026-08-25", model="gpt-5.6-sol", usage=None, event_time=None):
    return ParsedTokenEvent(
        event_key=key,
        event_time_utc=event_time or datetime(2026, 8, 24, 15, tzinfo=timezone.utc),
        local_date=day,
        model=model,
        usage=usage or TokenUsage(10, 4, 3, 1, 14),
        usage_source="last",
        session_hash="a" * 64,
        turn_hash="b" * 64,
        timestamp_fallback=False,
    )


def checkpoint():
    return Checkpoint(source_identity="source", normalized_path="safe", byte_offset=10)


def test_idempotent_aggregation_and_subset_totals(repository):
    event = make_event(usage=TokenUsage(100, 50, 80, 30, 150))
    assert repository.apply_batch(checkpoint(), [(event, 0)]) == (1, 0)
    assert repository.apply_batch(checkpoint(), [(event, 0)]) == (0, 1)
    totals = repository.query_totals("2026-08-25", "2026-08-25")
    assert totals["overall"] == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cached_input_tokens": 80,
        "reasoning_output_tokens": 30,
        "total_tokens": 150,
    }


def test_date_range_and_model_query(repository):
    repository.apply_batch(checkpoint(), [(make_event("e1", "2026-08-24", "gpt-5.6-sol"), 0)])
    repository.apply_batch(checkpoint(), [(make_event("e2", "2026-08-25", "gpt-5.6-terra"), 1)])
    repository.apply_batch(checkpoint(), [(make_event("e3", "2026-08-26", "other-model"), 2)])
    assert len(repository.query_daily("2026-08-24", "2026-08-25")) == 2
    assert [row["model"] for row in repository.query_daily("2026-08-24", "2026-08-26", "other-model")] == ["other-model"]


def test_unknown_model_is_recovered_only_from_one_model_in_the_same_turn(repository):
    unknown = make_event("unknown", model="unknown")
    hint = TurnModelHint(unknown.session_hash, unknown.turn_hash, "gpt-5.6-sol")
    repository.apply_batch(checkpoint(), [(unknown, 0)])
    repository.apply_batch(checkpoint(), [], model_hints=[hint])
    assert repository.query_daily("2026-08-25", "2026-08-25")[0]["model"] == "gpt-5.6-sol"

    conflicting = TurnModelHint(unknown.session_hash, unknown.turn_hash, "gpt-5.6-terra")
    repository.apply_batch(checkpoint(), [], model_hints=[conflicting])
    assert repository.query_daily("2026-08-25", "2026-08-25")[0]["model"] == "unknown"


def test_unknown_model_is_not_recovered_across_different_turns(repository):
    unknown = make_event("unknown", model="unknown")
    hint = TurnModelHint(unknown.session_hash, "c" * 64, "gpt-5.6-sol")
    repository.apply_batch(checkpoint(), [(unknown, 0)], model_hints=[hint])
    assert repository.query_daily("2026-08-25", "2026-08-25")[0]["model"] == "unknown"


def test_trend_uses_half_hour_ten_day_and_month_buckets(repository):
    events = [
        (make_event("e1", event_time=datetime(2026, 8, 25, 0, 10, tzinfo=timezone.utc)), 0),
        (make_event("e2", event_time=datetime(2026, 8, 25, 0, 40, tzinfo=timezone.utc)), 1),
        (make_event("e3", "2026-08-11", event_time=datetime(2026, 8, 11, tzinfo=timezone.utc)), 2),
        (make_event("e4", "2026-07-31", event_time=datetime(2026, 7, 31, tzinfo=timezone.utc)), 3),
    ]
    repository.apply_batch(checkpoint(), events)

    half_hour = repository.query_trend("2026-08-25", "2026-08-25", "30m")["buckets"]
    assert len(half_hour) == 48
    assert next(row for row in half_hour if row["label"] == "09:00")["total_tokens"] == 14
    assert next(row for row in half_hour if row["label"] == "09:30")["total_tokens"] == 14

    ten_day = repository.query_trend("2026-07-01", "2026-08-25", "10d")["buckets"]
    assert next(row for row in ten_day if row["key"] == "2026-08-11")["total_tokens"] == 14
    assert next(row for row in ten_day if row["key"] == "2026-07-21")["total_tokens"] == 14

    monthly = repository.query_trend("2026-07-01", "2026-08-25", "month")["buckets"]
    assert [row["key"] for row in monthly] == ["2026-07", "2026-08"]
    assert [row["total_tokens"] for row in monthly] == [14, 42]


def test_event_and_checkpoint_are_atomic(repository):
    bad = make_event("bad", usage=TokenUsage(-1, 0, 0, 0, 0))
    with pytest.raises(Exception):
        repository.apply_batch(checkpoint(), [(bad, 0)])
    assert repository.event_count() == 0
    assert repository.get_checkpoint("source") is None


def test_diagnostics_and_rebuild(repository):
    repository.apply_batch(checkpoint(), [(make_event(), 0)], Counter({"timestamp_fallback": 2}))
    assert repository.diagnostics()[0]["count"] == 2
    repository.rebuild_aggregates()
    assert repository.query_totals("2026-08-25", "2026-08-25")["overall"]["total_tokens"] == 14
    repository.reset_diagnostics()
    assert repository.diagnostics() == []


def test_csv_bom_columns_range_and_privacy(repository):
    repository.apply_batch(checkpoint(), [(make_event(model="gpt-5.6-luna"), 0)])
    body = create_csv(repository.query_daily("2026-08-25", "2026-08-25"))
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8-sig")
    assert text.splitlines()[0] == "날짜,모델,입력,출력,캐시 입력,추론 출력,전체 토큰"
    assert "gpt-5.6-luna" in text
    assert "session" not in text.lower()
    assert "prompt" not in text.lower()
