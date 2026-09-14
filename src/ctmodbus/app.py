"""Application ownership and ctui lifecycle integration."""

from importlib.metadata import version

from ctui import CtuiApp


class ModbusApp(CtuiApp):
    """A Modbus client with one connection and project-scoped services."""

    name = "ctmodbus"
    version = version("ctmodbus")
    description = "An asynchronous Modbus tool for device testing"
    prompt = "ctmodbus> "
    app_id = "io.controlthings.ctmodbus"
