"""Console entry point for the ctmodbus script and module execution.

Delegate argument parsing and runtime ownership to ModbusApp/ctui; importing
this module does not launch the application.
"""

from ctmodbus.app import ModbusApp


def main():
    """Run TUI without arguments or sequential -c/-f CLI commands from argv.

    ctui manages backend startup/shutdown. CLI raises SystemExit with status
    0 for success, 2 for command errors, or 1 for unexpected failures; TUI
    returns after exit. Ctrl-C completes async cleanup and exits 130 without a
    traceback. No live application is retained globally.
    """
    try:
        ModbusApp().run()
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
