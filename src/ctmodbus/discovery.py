"""Advisory local connection discovery and serial completion metadata.

Enumeration and process inspection are blocking. Async callers offload these
functions; discovered endpoints are suggestions, never an input allowlist.
"""

import asyncio

import psutil
from ctui import CompletionItem
from serial.tools.list_ports import comports
from tabulate import tabulate


def serial_devices():
    """Return pyserial port objects sorted by device path; OS errors propagate.

    Manufacturer/product metadata may be absent for non-USB or unsupported ports.
    This synchronous enumeration belongs on a worker thread for async callers.
    """
    return sorted(comports(), key=lambda item: item.device)


async def complete_serial(_context):
    """Return ctui CompletionItems after offloading port enumeration.

    Ignore the completion context. Insert only the device path; show available
    manufacturer/product as help, or a differing port description as fallback.
    Return an empty list when no ports exist; enumeration errors propagate.
    """
    results = []
    for item in await asyncio.to_thread(serial_devices):
        details = [value for value in (item.manufacturer, item.product) if value]
        if not details and item.description and item.description != item.device:
            details.append(item.description)
        results.append(CompletionItem(item.device, " — ".join(details)))
    return results


def suggestions():
    """Return serial-device and local-listener tables as plain text.

    Synchronous enumeration errors propagate. Process/network inspection is
    best effort: inaccessible process names become unavailable and global
    inspection errors become a diagnostic section rather than failing discovery.
    """
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
