from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, value: object) -> "TokenUsage | None":
        if not isinstance(value, dict):
            return None
        numbers: dict[str, int] = {}
        for key in TOKEN_FIELDS:
            raw = value.get(key, 0)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                return None
            number = int(raw)
            if number < 0:
                return None
            numbers[key] = number
        return cls(**numbers)

    def as_tuple(self) -> tuple[int, int, int, int, int]:
        return tuple(getattr(self, key) for key in TOKEN_FIELDS)  # type: ignore[return-value]

    def subtract_nonnegative(self, previous: "TokenUsage") -> "TokenUsage | None":
        values = [current - old for current, old in zip(self.as_tuple(), previous.as_tuple())]
        if any(value < 0 for value in values):
            return None
        return TokenUsage(**dict(zip(TOKEN_FIELDS, values)))

    def is_zero(self) -> bool:
        return not any(self.as_tuple())


@dataclass(slots=True)
class ParserState:
    session_hash: str = "unknown"
    turn_hash: str = "unknown"
    model: str = "unknown"
    cumulative: TokenUsage | None = None
    cumulative_segment: int = 0


@dataclass(frozen=True, slots=True)
class ParsedTokenEvent:
    event_key: str
    event_time_utc: datetime
    local_date: str
    model: str
    usage: TokenUsage
    usage_source: Literal["last", "total_delta", "total_baseline"]
    session_hash: str
    turn_hash: str
    timestamp_fallback: bool


@dataclass(frozen=True, slots=True)
class TurnModelHint:
    session_hash: str
    turn_hash: str
    model: str


@dataclass(slots=True)
class ParseOutcome:
    event: ParsedTokenEvent | None = None
    diagnostic_code: str | None = None
    model_hint: TurnModelHint | None = None


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    path: Path
    normalized_path: str
    identity: str
    size: int
    mtime_ns: int


@dataclass(slots=True)
class Checkpoint:
    source_identity: str
    normalized_path: str
    file_size: int = 0
    mtime_ns: int = 0
    byte_offset: int = 0
    last_line_start: int = 0
    last_line_hash: str = ""
    parser_state: ParserState = field(default_factory=ParserState)
    parser_version: int = 1


@dataclass(slots=True)
class ScanResult:
    files_discovered: int = 0
    files_scanned: int = 0
    complete_lines: int = 0
    inserted_events: int = 0
    duplicate_events: int = 0
    skipped_events: int = 0
    bytes_processed: int = 0
