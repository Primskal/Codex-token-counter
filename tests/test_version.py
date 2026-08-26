from __future__ import annotations

import tomllib
from pathlib import Path

from codex_token_monitor import __version__


def test_runtime_and_project_versions_match():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    assert __version__ == project["project"]["version"]
