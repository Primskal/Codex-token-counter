from __future__ import annotations

from codex_token_monitor.settings import AUTOSTART_VALUE_NAME, AutostartManager, validate_settings
from codex_token_monitor.single_instance import SingleInstance


class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


class FakeMutex:
    def __init__(self):
        self.taken = False

    def acquire(self, _name):
        if self.taken:
            return None
        self.taken = True
        return object()

    def release(self, _handle):
        self.taken = False


def test_autostart_register_and_remove_only_managed_entry(repository):
    registry = FakeRegistry()
    manager = AutostartManager(repository, registry)
    assert not manager.enabled()
    manager.set_enabled(True)
    managed = registry.get(AUTOSTART_VALUE_NAME)
    assert managed and manager.enabled()
    registry.set(AUTOSTART_VALUE_NAME, "user-replaced-command")
    manager.set_enabled(False)
    assert registry.get(AUTOSTART_VALUE_NAME) == "user-replaced-command"


def test_autostart_owned_entry_is_removed(repository):
    registry = FakeRegistry()
    manager = AutostartManager(repository, registry)
    manager.set_enabled(True)
    manager.set_enabled(False)
    assert AUTOSTART_VALUE_NAME not in registry.values


def test_single_instance_boundary():
    backend = FakeMutex()
    first = SingleInstance(backend=backend)
    second = SingleInstance(backend=backend)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_settings_validation_is_bounded(tmp_path):
    clean = validate_settings({
        "custom_log_paths": [str(tmp_path)],
        "backfill_days": -1,
        "scan_interval_seconds": 99999,
        "autostart_enabled": False,
    })
    assert "custom_log_paths" not in clean
    assert "backfill_days" not in clean
    assert clean["scan_interval_seconds"] == 3600
    assert clean["autostart_enabled"] is False
