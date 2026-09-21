"""Local serial discovery and completion tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ctmodbus.discovery import complete_serial


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_serial_completion_includes_usb_identity(self):
        ports = [
            SimpleNamespace(
                device="/dev/ttyUSB0",
                manufacturer="ControlThings",
                product="Modbus Adapter",
                description="USB serial device",
            ),
            SimpleNamespace(
                device="COM3",
                manufacturer=None,
                product=None,
                description="Built-in serial port",
            ),
        ]
        with patch("ctmodbus.discovery.serial_devices", return_value=ports):
            items = await complete_serial(None)

        self.assertEqual([item.value for item in items], ["/dev/ttyUSB0", "COM3"])
        self.assertEqual(items[0].help, "ControlThings — Modbus Adapter")
        self.assertEqual(items[1].help, "Built-in serial port")
