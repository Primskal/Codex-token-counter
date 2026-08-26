from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .models import ParseOutcome, ParsedTokenEvent, ParserState, TokenUsage
from .privacy import canonical_numeric_json, irreversible_hash


PARSER_SCHEMA_VERSION = 2
KST = ZoneInfo("Asia/Seoul")
_MAX_MODEL_LENGTH = 160


def _parse_timestamp(value: object, fallback: datetime) -> tuple[datetime, bool]:
    if isinstance(value, str):
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc), False
        except ValueError:
            pass
    return fallback.astimezone(timezone.utc), True


def _safe_model(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_MODEL_LENGTH or any(ord(char) < 32 for char in stripped):
        return "unknown"
    return stripped


class CodexEventParser:
    def __init__(
        self,
        source_mtime_utc: datetime,
        state: ParserState | None = None,
        source_instance: str = "unknown-source",
    ) -> None:
        self.source_mtime_utc = source_mtime_utc.astimezone(timezone.utc)
        self.state = state or ParserState()
        self.source_instance = source_instance

    def parse_bytes(self, raw: bytes) -> ParseOutcome:
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            return ParseOutcome(diagnostic_code="invalid_utf8")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return ParseOutcome(diagnostic_code="invalid_json")
        if not isinstance(value, dict):
            return ParseOutcome(diagnostic_code="unsupported_record")
        return self.parse_object(value)

    def parse_object(self, value: dict[str, object]) -> ParseOutcome:
        record_type = value.get("type")
        payload = value.get("payload")
        if not isinstance(payload, dict):
            return ParseOutcome()

        if record_type == "session_meta":
            raw_session = payload.get("session_id") or payload.get("id")
            self.state.session_hash = irreversible_hash("session", raw_session) if raw_session else "unknown"
            self.state.turn_hash = "unknown"
            self.state.model = "unknown"
            self.state.cumulative = None
            self.state.cumulative_segment = 0
            return ParseOutcome()

        if record_type == "turn_context":
            raw_turn = payload.get("turn_id")
            self.state.turn_hash = irreversible_hash("turn", self.state.session_hash, raw_turn) if raw_turn else "unknown"
            self.state.model = _safe_model(payload.get("model"))
            return ParseOutcome()

        if record_type != "event_msg" or payload.get("type") != "token_count":
            return ParseOutcome()

        info = payload.get("info")
        if not isinstance(info, dict):
            return ParseOutcome(diagnostic_code="token_missing_info")
        last = TokenUsage.from_mapping(info.get("last_token_usage"))
        total = TokenUsage.from_mapping(info.get("total_token_usage"))
        if last is None and total is None:
            return ParseOutcome(diagnostic_code="token_missing_usage")

        event_time, timestamp_fallback = _parse_timestamp(
            value.get("timestamp") or payload.get("timestamp"), self.source_mtime_utc
        )
        diagnostic = "timestamp_fallback" if timestamp_fallback else None

        previous_total = self.state.cumulative
        reset = False
        if total is not None and previous_total is not None:
            reset = total.subtract_nonnegative(previous_total) is None
            if reset:
                self.state.cumulative_segment += 1
        if total is not None:
            self.state.cumulative = total

        usage: TokenUsage
        usage_source: str
        if last is not None:
            usage = last
            usage_source = "last"
        elif previous_total is None or reset:
            # Establish a baseline. Counting it could double-count an unknown prior segment.
            return ParseOutcome(diagnostic_code="total_baseline")
        else:
            difference = total.subtract_nonnegative(previous_total) if total is not None else None
            if difference is None:
                return ParseOutcome(diagnostic_code="total_counter_reset")
            usage = difference
            usage_source = "total_delta"

        model = self.state.model or "unknown"
        usage_payload = dict(zip((
            "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens", "total_tokens"
        ), usage.as_tuple()))
        total_payload = None
        if total is not None:
            total_payload = dict(zip(usage_payload, total.as_tuple()))
        has_session_id = self.state.session_hash != "unknown"
        has_turn_id = self.state.turn_hash != "unknown"
        event_key = irreversible_hash(
            "token-event",
            self.state.session_hash,
            self.state.turn_hash,
            "stable-source" if has_session_id else self.source_instance,
            "stable-time" if has_turn_id else event_time.isoformat(),
            model,
            self.state.cumulative_segment,
            usage_source,
            canonical_numeric_json(usage_payload),
            canonical_numeric_json(total_payload or {}),
        )
        event = ParsedTokenEvent(
            event_key=event_key,
            event_time_utc=event_time,
            local_date=event_time.astimezone(KST).date().isoformat(),
            model=model,
            usage=usage,
            usage_source=usage_source,  # type: ignore[arg-type]
            session_hash=self.state.session_hash,
            turn_hash=self.state.turn_hash,
            timestamp_fallback=timestamp_fallback,
        )
        return ParseOutcome(event=event, diagnostic_code=diagnostic)


def parser_state_to_json(state: ParserState) -> str:
    payload = {
        "session_hash": state.session_hash,
        "turn_hash": state.turn_hash,
        "model": state.model,
        "cumulative": asdict(state.cumulative) if state.cumulative else None,
        "cumulative_segment": state.cumulative_segment,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parser_state_from_json(value: str | None) -> ParserState:
    if not value:
        return ParserState()
    try:
        payload = json.loads(value)
        cumulative = TokenUsage.from_mapping(payload.get("cumulative")) if payload.get("cumulative") else None
        return ParserState(
            session_hash=str(payload.get("session_hash") or "unknown"),
            turn_hash=str(payload.get("turn_hash") or "unknown"),
            model=_safe_model(payload.get("model")),
            cumulative=cumulative,
            cumulative_segment=max(0, int(payload.get("cumulative_segment", 0))),
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return ParserState()
