from codex_token_monitor.dpi import enable_per_monitor_dpi_awareness

# Keep this before importing the rest of the application so development and
# packaged runs establish the fallback before pystray or any UI object exists.
enable_per_monitor_dpi_awareness()

from codex_token_monitor.app import main


if __name__ == "__main__":
    raise SystemExit(main())
