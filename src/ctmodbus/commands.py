"""Console entry point for the ctmodbus script and module execution.

Delegate argument parsing and runtime ownership to ModbusApp/ctui; importing
this module does not launch the application.
"""

from ctmodbus.app import ModbusApp


def main():
    """Run TUI without arguments or sequential -c/-f CLI commands from argv.

    ctui manages backend startup/shutdown. CLI raises SystemExit with status
    0 for success, 2 for command errors, or 1 for unexpected failures; TUI
    returns after exit. No live application is retained globally.
    """
    ModbusApp().run()


if __name__ == "__main__":
    main()
