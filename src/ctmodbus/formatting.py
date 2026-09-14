"""Pure formatting for identical TUI and command-line results."""

from datetime import datetime, timezone
from itertools import groupby

from tabulate import tabulate


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def format_values(kind, values):
    """Summarize consecutive equal values without hiding address gaps or order."""
    bits = kind in ("coils", "discrete_inputs")
    rows = []
    for _, group in groupby(
        enumerate(values), key=lambda pair: (pair[1][0] - pair[0], pair[1][1])
    ):
        items = [item for _, item in group]
        start, value = items[0]
        stop = items[-1][0]
        address = str(start) if start == stop else f"{start}-{stop}"
        row = [address, int(value)]
        if not bits:
            # This is a code point view, not a claim that one register is UTF-8.
            char = chr(value)
            row.extend(
                [f"{value:04X}", ascii(char)[1:-1] if not char.isprintable() else char]
            )
        rows.append(row)
    return tabulate(
        rows,
        headers=(
            ["Address", "Bit"] if bits else ["Address", "Integer", "Hex", "Character"]
        ),
    )


def format_identification(information):
    names = (
        "VendorName",
        "ProductCode",
        "MajorMinorRevision",
        "VendorUrl",
        "ProductName",
        "ModelName",
        "UserApplicationName",
    )
    rows = []
    for object_id, value in sorted(information.items()):
        label = (
            names[object_id] if 0 <= object_id < len(names) else f"ObjectID {object_id}"
        )
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="backslashreplace")
        # repr escapes device-provided terminal control sequences.
        rows.append([object_id, label, repr(str(value))])
    return tabulate(rows, headers=["ID", "Object", "Value"])
