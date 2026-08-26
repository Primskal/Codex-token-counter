from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = r"Local\CodexTokenMonitor-v1", backend: object | None = None) -> None:
        self.name = name
        self.backend = backend
        self.handle: object | None = None

    def acquire(self) -> bool:
        if self.handle is not None:
            return True
        if self.backend is not None:
            self.handle = self.backend.acquire(self.name)  # type: ignore[attr-defined]
            return self.handle is not None
        if os.name != "nt":
            raise RuntimeError("Codex Token Monitor는 Windows 전용입니다.")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        if self.backend is not None:
            self.backend.release(self.handle)  # type: ignore[attr-defined]
        elif os.name == "nt":
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self.handle)
        self.handle = None

    def __enter__(self) -> "SingleInstance":
        if not self.acquire():
            raise RuntimeError("이미 Codex Token Monitor가 실행 중입니다.")
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

