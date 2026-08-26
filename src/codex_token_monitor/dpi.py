"""Early, best-effort DPI awareness fallback for development launches.

The packaged application declares this in its PE manifest.  Windows applies
that declaration before Python starts; this fallback only covers an unmanifested
``python -m codex_token_monitor`` development launch.
"""

from __future__ import annotations

import ctypes
import os


PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
PROCESS_PER_MONITOR_DPI_AWARE = 2
E_ACCESSDENIED = 0x80070005


def enable_per_monitor_dpi_awareness() -> bool:
    """Request the strongest supported per-monitor DPI mode before UI creation.

    A manifest may have set the process mode already. In that expected case
    Windows rejects the duplicate request with ``E_ACCESSDENIED`` and no action
    is required.
    """
    if os.name != "nt":
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_context = getattr(user32, "SetProcessDpiAwarenessContext", None)
    if set_context is not None:
        set_context.argtypes = (ctypes.c_void_p,)
        set_context.restype = ctypes.c_int
        if set_context(PER_MONITOR_AWARE_V2):
            return True

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
    except OSError:
        shcore = None
    if shcore is not None:
        set_awareness = shcore.SetProcessDpiAwareness
        set_awareness.argtypes = (ctypes.c_int,)
        set_awareness.restype = ctypes.c_long
        result = set_awareness(PROCESS_PER_MONITOR_DPI_AWARE)
        if result == 0:
            return True
        if result & 0xFFFFFFFF == E_ACCESSDENIED:
            return False

    set_legacy = user32.SetProcessDPIAware
    set_legacy.argtypes = ()
    set_legacy.restype = ctypes.c_int
    return bool(set_legacy())
