from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

from .repository import Repository


AUTOSTART_VALUE_NAME = "CodexTokenMonitor"


class RegistryBackend(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WindowsRunRegistry:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def get(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def set(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


def current_launch_command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --startup'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{executable.resolve()}" -m codex_token_monitor --startup'


class AutostartManager:
    def __init__(self, repository: Repository, registry: RegistryBackend | None = None) -> None:
        self.repository = repository
        self.registry = registry or WindowsRunRegistry()

    def enabled(self) -> bool:
        managed = self.repository.get_setting("autostart_managed_command", None)
        actual = self.registry.get(AUTOSTART_VALUE_NAME)
        return isinstance(managed, str) and actual == managed

    def set_enabled(self, enabled: bool) -> bool:
        if enabled:
            command = current_launch_command()
            self.registry.set(AUTOSTART_VALUE_NAME, command)
            self.repository.set_setting("autostart_managed_command", command)
            return True
        managed = self.repository.get_setting("autostart_managed_command", None)
        actual = self.registry.get(AUTOSTART_VALUE_NAME)
        if isinstance(managed, str) and actual == managed:
            self.registry.delete(AUTOSTART_VALUE_NAME)
        self.repository.set_setting("autostart_managed_command", None)
        return False


def validate_settings(payload: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    try:
        result["scan_interval_seconds"] = max(2, min(3600, int(payload.get("scan_interval_seconds", 15))))
    except (TypeError, ValueError):
        raise ValueError("재조정 간격은 숫자여야 합니다.") from None
    if "autostart_enabled" in payload:
        result["autostart_enabled"] = bool(payload["autostart_enabled"])
    return result
