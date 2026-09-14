"""Local connection suggestions, performed off the event loop."""

import asyncio

import psutil
from serial.tools.list_ports import comports
from tabulate import tabulate


def serial_devices():
    """Enumerate ports in a stable display order."""
    return sorted(comports(), key=lambda item: item.device)


async def complete_serial(_context):
    """ctui async completion provider; discovery is advisory, not a restriction."""
    return [item.device for item in await asyncio.to_thread(serial_devices)]


def suggestions():
    """Format local devices and best-effort process inspection."""
    devices = [
        [item.device, item.manufacturer or "", item.product or ""]
        for item in serial_devices()
    ]
    sections = [
        "Connected serial devices",
        tabulate(devices, headers=["Device", "Manufacturer", "Product"]),
    ]
    rows = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            process = ""
            if conn.pid:
                try:
                    process = psutil.Process(conn.pid).name()
                except (psutil.Error, OSError):
                    process = "unavailable"
            rows.append([conn.laddr.ip, conn.laddr.port, process])
        sections.extend(
            [
                "Local listening services",
                tabulate(
                    sorted(rows, key=lambda row: (row[1], row[0])),
                    headers=["IP", "Port", "Process"],
                ),
            ]
        )
    except (psutil.Error, OSError) as error:
        sections.append(f"Local listening services unavailable: {error}")
    return "\n\n".join(sections)
