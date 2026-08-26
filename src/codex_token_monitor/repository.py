from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .models import Checkpoint, ParsedTokenEvent, TOKEN_FIELDS, TurnModelHint
from .parser import KST, PARSER_SCHEMA_VERSION, parser_state_from_json, parser_state_to_json


DB_SCHEMA_VERSION = 2


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_lock = threading.Lock()
        self._migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._migration_lock, self.connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > DB_SCHEMA_VERSION:
                raise RuntimeError("지원하지 않는 최신 데이터베이스 스키마입니다.")
            if current < 1:
                connection.executescript(
                    """
                    BEGIN;
                    CREATE TABLE IF NOT EXISTS file_checkpoints (
                        source_identity TEXT PRIMARY KEY,
                        normalized_path TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        byte_offset INTEGER NOT NULL,
                        last_line_start INTEGER NOT NULL,
                        last_line_hash TEXT NOT NULL,
                        parser_state_json TEXT NOT NULL,
                        parser_version INTEGER NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_checkpoints_path ON file_checkpoints(normalized_path);

                    CREATE TABLE IF NOT EXISTS processed_events (
                        event_key TEXT PRIMARY KEY,
                        event_time_utc TEXT NOT NULL,
                        source_identity TEXT NOT NULL,
                        source_offset INTEGER NOT NULL,
                        parser_version INTEGER NOT NULL,
                        inserted_at_utc TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS token_events (
                        event_key TEXT PRIMARY KEY REFERENCES processed_events(event_key) ON DELETE CASCADE,
                        local_date TEXT NOT NULL,
                        model TEXT NOT NULL,
                        session_hash TEXT NOT NULL,
                        turn_hash TEXT NOT NULL,
                        usage_source TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
                        output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
                        cached_input_tokens INTEGER NOT NULL CHECK(cached_input_tokens >= 0),
                        reasoning_output_tokens INTEGER NOT NULL CHECK(reasoning_output_tokens >= 0),
                        total_tokens INTEGER NOT NULL CHECK(total_tokens >= 0),
                        timestamp_fallback INTEGER NOT NULL CHECK(timestamp_fallback IN (0, 1))
                    );
                    CREATE INDEX IF NOT EXISTS idx_token_events_date_model ON token_events(local_date, model);

                    CREATE TABLE IF NOT EXISTS daily_model_aggregates (
                        local_date TEXT NOT NULL,
                        model TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL,
                        cached_input_tokens INTEGER NOT NULL,
                        reasoning_output_tokens INTEGER NOT NULL,
                        total_tokens INTEGER NOT NULL,
                        event_count INTEGER NOT NULL,
                        PRIMARY KEY(local_date, model)
                    );

                    CREATE TABLE IF NOT EXISTS diagnostic_counters (
                        code TEXT PRIMARY KEY,
                        count INTEGER NOT NULL,
                        last_seen_utc TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    );
                    PRAGMA user_version=1;
                    COMMIT;
                    """
                )
                current = 1
            if current < 2:
                connection.executescript(
                    """
                    BEGIN;
                    ALTER TABLE token_events ADD COLUMN model_inferred INTEGER NOT NULL DEFAULT 0
                        CHECK(model_inferred IN (0, 1));
                    CREATE TABLE turn_model_hints (
                        session_hash TEXT NOT NULL,
                        turn_hash TEXT NOT NULL,
                        model TEXT NOT NULL,
                        PRIMARY KEY(session_hash, turn_hash, model)
                    );
                    CREATE INDEX idx_turn_model_hints_turn
                        ON turn_model_hints(session_hash, turn_hash);
                    PRAGMA user_version=2;
                    COMMIT;
                    """
                )

    def get_checkpoint(self, source_identity: str) -> Checkpoint | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM file_checkpoints WHERE source_identity=?", (source_identity,)
            ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            source_identity=row["source_identity"],
            normalized_path=row["normalized_path"],
            file_size=row["file_size"],
            mtime_ns=row["mtime_ns"],
            byte_offset=row["byte_offset"],
            last_line_start=row["last_line_start"],
            last_line_hash=row["last_line_hash"],
            parser_state=parser_state_from_json(row["parser_state_json"]),
            parser_version=row["parser_version"],
        )

    def get_checkpoint_by_path(self, normalized_path: str) -> Checkpoint | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT source_identity FROM file_checkpoints WHERE normalized_path=? ORDER BY updated_at_utc DESC LIMIT 1",
                (normalized_path,),
            ).fetchone()
        return self.get_checkpoint(row["source_identity"]) if row else None

    def apply_batch(
        self,
        checkpoint: Checkpoint,
        events: Iterable[tuple[ParsedTokenEvent, int]],
        diagnostics: Counter[str] | None = None,
        model_hints: Iterable[TurnModelHint] = (),
    ) -> tuple[int, int]:
        inserted = 0
        duplicates = 0
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as connection:
            touched_turns: set[tuple[str, str]] = set()
            for event, source_offset in events:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO processed_events
                       (event_key,event_time_utc,source_identity,source_offset,parser_version,inserted_at_utc)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        event.event_key,
                        event.event_time_utc.isoformat(),
                        checkpoint.source_identity,
                        source_offset,
                        PARSER_SCHEMA_VERSION,
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    duplicates += 1
                    continue
                usage = event.usage
                connection.execute(
                    """INSERT INTO token_events
                       (event_key,local_date,model,session_hash,turn_hash,usage_source,
                        input_tokens,output_tokens,cached_input_tokens,reasoning_output_tokens,total_tokens,timestamp_fallback)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event.event_key,
                        event.local_date,
                        event.model,
                        event.session_hash,
                        event.turn_hash,
                        event.usage_source,
                        *usage.as_tuple(),
                        int(event.timestamp_fallback),
                    ),
                )
                if event.session_hash != "unknown" and event.turn_hash != "unknown":
                    touched_turns.add((event.session_hash, event.turn_hash))
                connection.execute(
                    """INSERT INTO daily_model_aggregates
                       (local_date,model,input_tokens,output_tokens,cached_input_tokens,
                        reasoning_output_tokens,total_tokens,event_count)
                       VALUES(?,?,?,?,?,?,?,1)
                       ON CONFLICT(local_date,model) DO UPDATE SET
                         input_tokens=input_tokens+excluded.input_tokens,
                         output_tokens=output_tokens+excluded.output_tokens,
                         cached_input_tokens=cached_input_tokens+excluded.cached_input_tokens,
                         reasoning_output_tokens=reasoning_output_tokens+excluded.reasoning_output_tokens,
                         total_tokens=total_tokens+excluded.total_tokens,
                         event_count=event_count+1""",
                    (event.local_date, event.model, *usage.as_tuple()),
                )
                inserted += 1
            for hint in model_hints:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO turn_model_hints(session_hash,turn_hash,model)
                       VALUES(?,?,?)""",
                    (hint.session_hash, hint.turn_hash, hint.model),
                )
                if cursor.rowcount:
                    touched_turns.add((hint.session_hash, hint.turn_hash))
            inferred_changed = False
            for session_hash, turn_hash in touched_turns:
                candidate_rows = connection.execute(
                    """SELECT model FROM turn_model_hints WHERE session_hash=? AND turn_hash=?
                       UNION
                       SELECT model FROM token_events
                       WHERE session_hash=? AND turn_hash=? AND model!='unknown' AND model_inferred=0""",
                    (session_hash, turn_hash, session_hash, turn_hash),
                ).fetchall()
                candidates = {str(row["model"]) for row in candidate_rows}
                resolved_model = next(iter(candidates)) if len(candidates) == 1 else "unknown"
                inferred = int(len(candidates) == 1)
                repair_rows = connection.execute(
                    """SELECT event_key,model,model_inferred FROM token_events
                       WHERE session_hash=? AND turn_hash=? AND (model='unknown' OR model_inferred=1)""",
                    (session_hash, turn_hash),
                ).fetchall()
                for row in repair_rows:
                    if row["model"] == resolved_model and int(row["model_inferred"]) == inferred:
                        continue
                    connection.execute(
                        "UPDATE token_events SET model=?,model_inferred=? WHERE event_key=?",
                        (resolved_model, inferred, row["event_key"]),
                    )
                    inferred_changed = True
            if inferred_changed:
                self._rebuild_aggregates(connection)
            for code, count in (diagnostics or {}).items():
                connection.execute(
                    """INSERT INTO diagnostic_counters(code,count,last_seen_utc) VALUES(?,?,?)
                       ON CONFLICT(code) DO UPDATE SET count=count+excluded.count,last_seen_utc=excluded.last_seen_utc""",
                    (code, count, now),
                )
            connection.execute(
                """INSERT INTO file_checkpoints
                   (source_identity,normalized_path,file_size,mtime_ns,byte_offset,last_line_start,last_line_hash,
                    parser_state_json,parser_version,updated_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_identity) DO UPDATE SET
                     normalized_path=excluded.normalized_path,file_size=excluded.file_size,
                     mtime_ns=excluded.mtime_ns,byte_offset=excluded.byte_offset,
                     last_line_start=excluded.last_line_start,last_line_hash=excluded.last_line_hash,
                     parser_state_json=excluded.parser_state_json,parser_version=excluded.parser_version,
                     updated_at_utc=excluded.updated_at_utc""",
                (
                    checkpoint.source_identity,
                    checkpoint.normalized_path,
                    checkpoint.file_size,
                    checkpoint.mtime_ns,
                    checkpoint.byte_offset,
                    checkpoint.last_line_start,
                    checkpoint.last_line_hash,
                    parser_state_to_json(checkpoint.parser_state),
                    checkpoint.parser_version,
                    now,
                ),
            )
        return inserted, duplicates

    def increment_diagnostic(self, code: str, count: int = 1) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO diagnostic_counters(code,count,last_seen_utc) VALUES(?,?,?)
                   ON CONFLICT(code) DO UPDATE SET count=count+excluded.count,last_seen_utc=excluded.last_seen_utc""",
                (code, count, now),
            )

    def query_daily(self, start_date: str, end_date: str, model: str | None = None) -> list[dict[str, object]]:
        sql = """SELECT local_date AS date,model,input_tokens,output_tokens,cached_input_tokens,
                        reasoning_output_tokens,total_tokens,event_count
                 FROM daily_model_aggregates WHERE local_date BETWEEN ? AND ?"""
        parameters: list[object] = [start_date, end_date]
        if model:
            sql += " AND model=?"
            parameters.append(model)
        sql += " ORDER BY local_date, model"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, parameters)]

    def query_totals(self, start_date: str, end_date: str) -> dict[str, object]:
        rows = self.query_daily(start_date, end_date)
        by_model: dict[str, dict[str, int]] = {}
        by_date: dict[str, dict[str, int]] = {}
        overall = {field: 0 for field in TOKEN_FIELDS}
        for row in rows:
            for group, key in ((by_model, str(row["model"])), (by_date, str(row["date"]))):
                target = group.setdefault(key, {field: 0 for field in TOKEN_FIELDS})
                for field in TOKEN_FIELDS:
                    target[field] += int(row[field])
            for field in TOKEN_FIELDS:
                overall[field] += int(row[field])
        return {"rows": rows, "by_model": by_model, "by_date": by_date, "overall": overall}

    def query_trend(self, start_date: str, end_date: str, granularity: str = "day") -> dict[str, object]:
        if granularity not in {"30m", "day", "10d", "month"}:
            raise ValueError("지원하지 않는 추세 집계 단위입니다.")
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        buckets: dict[str, dict[str, object]] = {}

        def bucket_for_day(day: date) -> tuple[str, str]:
            if granularity == "month":
                return day.strftime("%Y-%m"), day.strftime("%Y.%m")
            if granularity == "10d":
                segment = 1 if day.day <= 10 else 11 if day.day <= 20 else 21
                key = f"{day:%Y-%m}-{segment:02d}"
                suffix = "01–10" if segment == 1 else "11–20" if segment == 11 else "21–말일"
                return key, f"{day:%m}.{suffix}"
            return day.isoformat(), day.strftime("%m-%d")

        def ensure_bucket(key: str, label: str) -> dict[str, object]:
            return buckets.setdefault(key, {"key": key, "label": label, "total_tokens": 0, "models": {}})

        day = start
        while day <= end:
            if granularity == "30m":
                for hour in range(24):
                    for minute in (0, 30):
                        key = f"{day.isoformat()} {hour:02d}:{minute:02d}"
                        ensure_bucket(key, f"{hour:02d}:{minute:02d}")
            else:
                ensure_bucket(*bucket_for_day(day))
            day += timedelta(days=1)

        if granularity == "30m":
            sql = """SELECT p.event_time_utc,t.model,t.total_tokens
                     FROM token_events AS t
                     JOIN processed_events AS p ON p.event_key=t.event_key
                     WHERE t.local_date BETWEEN ? AND ?
                     ORDER BY p.event_time_utc,t.model"""
            with self.connect() as connection:
                rows = connection.execute(sql, (start_date, end_date)).fetchall()
            values = []
            for row in rows:
                event_time = datetime.fromisoformat(str(row["event_time_utc"])).astimezone(KST)
                minute = 0 if event_time.minute < 30 else 30
                key = f"{event_time.date().isoformat()} {event_time.hour:02d}:{minute:02d}"
                values.append((key, str(row["model"]), int(row["total_tokens"])))
        else:
            values = []
            for row in self.query_daily(start_date, end_date):
                key, _label = bucket_for_day(date.fromisoformat(str(row["date"])))
                values.append((key, str(row["model"]), int(row["total_tokens"])))

        for key, model, token_count in values:
            bucket = buckets.get(key)
            if bucket is None:
                continue
            bucket["total_tokens"] = int(bucket["total_tokens"]) + token_count
            models = bucket["models"]
            assert isinstance(models, dict)
            models[model] = int(models.get(model, 0)) + token_count
        return {"granularity": granularity, "buckets": list(buckets.values())}

    def diagnostics(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT code,count,last_seen_utc FROM diagnostic_counters ORDER BY code"
            )]

    def reset_diagnostics(self) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM diagnostic_counters")

    def event_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM token_events").fetchone()[0])

    def get_setting(self, key: str, default: object = None) -> object:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: object) -> None:
        now = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO app_settings(key,value,updated_at_utc) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at_utc=excluded.updated_at_utc""",
                (key, serialized, now),
            )

    def all_settings(self) -> dict[str, object]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key,value FROM app_settings").fetchall()
        result: dict[str, object] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                continue
        return result

    def rebuild_aggregates(self) -> None:
        with self.transaction() as connection:
            self._rebuild_aggregates(connection)

    @staticmethod
    def _rebuild_aggregates(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM daily_model_aggregates")
        connection.execute(
            """INSERT INTO daily_model_aggregates
               SELECT local_date,model,SUM(input_tokens),SUM(output_tokens),SUM(cached_input_tokens),
                      SUM(reasoning_output_tokens),SUM(total_tokens),COUNT(*)
               FROM token_events GROUP BY local_date,model"""
        )
