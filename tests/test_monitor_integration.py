from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from codex_token_monitor.discovery import identify_source
from codex_token_monitor.monitor import MonitorService
from codex_token_monitor.repository import Repository

from conftest import session, token, turn, usage, write_jsonl


def setup_monitor(tmp_path: Path):
    root = tmp_path / "logs"
    root.mkdir()
    repo = Repository(tmp_path / "data" / "monitor.db")
    monitor = MonitorService(repo, batch_lines=2, roots_override=[root])
    return root, repo, monitor


def base_records(model="gpt-5.6-sol"):
    return [session(), turn(model), token()]


def test_normal_append_restart_and_idempotence(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "session.jsonl"
    write_jsonl(path, base_records())
    first = monitor.run_once(True)
    assert first.inserted_events == 1 and repo.event_count() == 1
    second_event = token(last=usage(5, 2, 1, 1, 7), total=usage(15, 6, 4, 2, 21), timestamp="2026-08-24T10:01:00Z")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(second_event) + "\n")
    # No watchdog hint: periodic reconciliation still recovers the append.
    second = monitor.run_once()
    assert second.inserted_events == 1 and repo.event_count() == 2
    restarted = MonitorService(Repository(repo.db_path), roots_override=[root])
    third = restarted.run_once()
    assert third.inserted_events == 0 and repo.event_count() == 2


def test_partial_line_is_retried_after_completion(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "partial.jsonl"
    write_jsonl(path, [session(), turn()], final_newline=True)
    raw = json.dumps(token(), ensure_ascii=False).encode("utf-8")
    with path.open("ab") as stream:
        stream.write(raw[:-5])
    monitor.run_once()
    cp = repo.get_checkpoint(identify_source(path).identity)
    assert cp and cp.byte_offset < path.stat().st_size and repo.event_count() == 0
    with path.open("ab") as stream:
        stream.write(raw[-5:] + b"\n")
    monitor.run_once()
    assert repo.event_count() == 1


def test_truncate_same_file_rescans_without_double_count(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "truncate.jsonl"
    write_jsonl(path, base_records())
    monitor.run_once()
    write_jsonl(path, base_records())  # same file identity, shorter/equal replacement content
    os.truncate(path, max(1, path.stat().st_size - 1))
    monitor.run_once()
    with path.open("ab") as stream:
        stream.write(b"\n")
    monitor.run_once()
    assert repo.event_count() == 1
    assert any(row["code"] in {"file_truncated", "file_replaced"} for row in repo.diagnostics())


def test_rename_and_archive_move_preserve_checkpoint(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "active.jsonl"
    write_jsonl(path, base_records())
    identity = identify_source(path).identity
    monitor.run_once()
    archive = root / "archive"
    archive.mkdir()
    moved = archive / "archived.jsonl"
    path.rename(moved)
    assert identify_source(moved).identity == identity
    monitor.run_once()
    cp = repo.get_checkpoint(identity)
    assert cp and cp.normalized_path.endswith("archived.jsonl")
    assert repo.event_count() == 1
    assert any(row["code"] == "file_moved" for row in repo.diagnostics())


def test_same_history_copied_to_another_path_is_deduplicated(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    source = root / "one.jsonl"
    copy = root / "two.jsonl"
    write_jsonl(source, base_records())
    shutil.copyfile(source, copy)
    result = monitor.run_once()
    assert repo.event_count() == 1
    assert result.inserted_events == 1 and result.duplicate_events == 1


def test_history_without_turn_id_deduplicates_by_session_and_timestamp(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    records = [session(), token()]
    write_jsonl(root / "fork-a.jsonl", records)
    write_jsonl(root / "fork-b.jsonl", records)
    monitor.run_once()
    assert repo.event_count() == 1
    assert repo.query_daily("2026-08-24", "2026-08-24")[0]["model"] == "unknown"


def test_file_replacement_new_identity_and_rotation(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "same.jsonl"
    write_jsonl(path, base_records())
    monitor.run_once()
    path.unlink()
    write_jsonl(path, [session("new-session"), turn(turn_id="new-turn"), token(last=usage(7, 3, 2, 1, 10), total=usage(7, 3, 2, 1, 10))])
    monitor.run_once()
    assert repo.event_count() == 2
    assert any(row["code"] == "file_replaced" for row in repo.diagnostics())


def test_crash_before_and_after_transaction_recovery(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "crash.jsonl"
    write_jsonl(path, base_records())
    # Before applying anything, a fresh process simply scans from byte zero.
    recovered = MonitorService(Repository(repo.db_path), roots_override=[root])
    assert recovered.run_once().inserted_events == 1
    # After the atomic commit, another process resumes at the checkpoint.
    recovered_again = MonitorService(Repository(repo.db_path), roots_override=[root])
    assert recovered_again.run_once().inserted_events == 0
    assert repo.event_count() == 1


def test_model_switch_aggregation(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    path = root / "models.jsonl"
    records = base_records("gpt-5.6-sol") + [
        turn("gpt-5.6-luna", "turn-2"),
        token(last=usage(2, 1, 1, 0, 3), total=usage(12, 5, 4, 1, 17), timestamp="2026-08-24T10:03:00Z"),
    ]
    write_jsonl(path, records)
    monitor.run_once()
    rows = repo.query_daily("2026-08-24", "2026-08-25")
    assert {row["model"] for row in rows} == {"gpt-5.6-sol", "gpt-5.6-luna"}


def test_repeated_turn_context_recovers_unknown_model_for_same_turn(tmp_path):
    root, repo, monitor = setup_monitor(tmp_path)
    records = [
        session(),
        turn("", "turn-1"),
        token(),
        turn("gpt-5.6-sol", "turn-1"),
    ]
    write_jsonl(root / "recover-model.jsonl", records)
    monitor.run_once()
    rows = repo.query_daily("2026-08-24", "2026-08-24")
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-5.6-sol"
