"""Console entry point."""

from ctmodbus.app import ModbusApp


def main():
    """Run the terminal UI or ctui's automatic command-line interface."""
    ModbusApp().run()


if __name__ == "__main__":
    main()
