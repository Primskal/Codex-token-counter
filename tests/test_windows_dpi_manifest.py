from __future__ import annotations

import ctypes
import os
from pathlib import Path
from xml.etree import ElementTree

import pytest


RT_MANIFEST = 24
LOAD_LIBRARY_AS_DATAFILE = 0x00000002


def read_embedded_manifest(executable: Path) -> str:
    """Read manifest resource #1 directly from a Windows PE executable."""
    if os.name != "nt":
        pytest.skip("Windows PE manifest inspection requires Windows")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.argtypes = (ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint)
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    kernel32.FindResourceW.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    kernel32.FindResourceW.restype = ctypes.c_void_p
    kernel32.SizeofResource.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.SizeofResource.restype = ctypes.c_uint32
    kernel32.LoadResource.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.LoadResource.restype = ctypes.c_void_p
    kernel32.LockResource.argtypes = (ctypes.c_void_p,)
    kernel32.LockResource.restype = ctypes.c_void_p
    kernel32.FreeLibrary.argtypes = (ctypes.c_void_p,)
    kernel32.FreeLibrary.restype = ctypes.c_int

    module = kernel32.LoadLibraryExW(str(executable), None, LOAD_LIBRARY_AS_DATAFILE)
    if not module:
        raise OSError(ctypes.get_last_error(), f"Could not load {executable}")
    try:
        resource = kernel32.FindResourceW(module, ctypes.c_void_p(1), ctypes.c_void_p(RT_MANIFEST))
        if not resource:
            raise OSError(ctypes.get_last_error(), f"No manifest resource in {executable}")
        size = kernel32.SizeofResource(module, resource)
        data = kernel32.LoadResource(module, resource)
        pointer = kernel32.LockResource(data)
        return ctypes.string_at(pointer, size).decode("utf-8-sig")
    finally:
        kernel32.FreeLibrary(module)


def test_release_executable_declares_per_monitor_v2_dpi_awareness() -> None:
    executable = Path(os.environ.get(
        "CODEX_TOKEN_MONITOR_RELEASE_EXE",
        Path(__file__).resolve().parents[1] / "dist" / "CodexTokenMonitor.exe",
    ))
    if not executable.is_file():
        pytest.skip("Release executable has not been built yet; build.ps1 runs this check after packaging.")

    root = ElementTree.fromstring(read_embedded_manifest(executable))
    current = root.find(".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness")
    legacy = root.find(".//{http://schemas.microsoft.com/SMI/2005/WindowsSettings}dpiAware")

    assert current is not None
    assert current.text == "PerMonitorV2,PerMonitor,System"
    assert legacy is not None
    assert legacy.text == "true/pm"
