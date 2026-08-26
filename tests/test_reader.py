from __future__ import annotations

from codex_token_monitor.reader import iter_complete_lines


def test_append_partial_line_and_utf8_boundary(tmp_path):
    path = tmp_path / "a.jsonl"
    prefix = '{"text":"한글🙂"}'
    encoded = prefix.encode("utf-8")
    path.write_bytes(encoded[:-2])
    assert list(iter_complete_lines(path, 0, chunk_size=3)) == []
    with path.open("ab") as stream:
        stream.write(encoded[-2:] + b"\n")
    lines = list(iter_complete_lines(path, 0, chunk_size=3))
    assert len(lines) == 1
    assert lines[0].raw.decode("utf-8") == prefix


def test_only_new_lines_are_read(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(b"one\ntwo\n")
    first = list(iter_complete_lines(path))
    with path.open("ab") as stream:
        stream.write(b"three\n")
    second = list(iter_complete_lines(path, first[-1].end))
    assert [line.raw for line in second] == [b"three"]

