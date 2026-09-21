"""Pure formatting for identical TUI and command-line results.

Return strings without changing device/project state. Callers provide validated
wire values; rendering escapes control characters and uses explicit UTC times.
"""

from datetime import datetime, timezone
from itertools import groupby

from tabulate import tabulate


def timestamp():
    """Return an unambiguous UTC timestamp for protocol output."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def format_values(kind, values):
    """Return a table of ordered (address, value) pairs for a canonical table.

    Collapse adjacent equal values without hiding gaps, repeats, or input order.
    Bit tables show 0/1; registers add hex and one Unicode code point (not UTF-8
    decoding). Escape nonprintable characters. Caller validates wire ranges;
    malformed pairs or values can raise ordinary Python conversion errors.
    """
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
    """Return an ID-sorted table from a validated object-ID/value mapping.

    Label standard IDs 0–6 and retain sparse vendor IDs. Decode byte strings
    using UTF-8 with escaped invalid bytes and repr all values to escape
    terminal controls. Perform no protocol validation or I/O.
    """
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
