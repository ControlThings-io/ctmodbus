"""Shared integer literal syntax for tag values and register writes."""

import re

INTEGER_PATTERN = re.compile(
    r"(?P<sign>[+-]?)(?:(?P<prefix>0[bBoOdDxX])(?P<digits>[0-9A-Fa-f_]+)|"
    r"(?P<decimal>[0-9][0-9_]*))\Z"
)


def parse_integer(text: str) -> int:
    """Parse decimal or 0b/0o/0d/0x text with an optional sign and underscores.

    Malformed text or digits invalid for the radix raise ValueError. This parser
    imposes no width or range; callers handle bounds and two's-complement bits.
    """
    match = INTEGER_PATTERN.fullmatch(text)
    if not match:
        raise ValueError("expected an integer or 0b/0o/0d/0x literal")
    digits = (match.group("digits") or match.group("decimal")).replace("_", "")
    prefix = (match.group("prefix") or "0d").lower()
    base = {"0b": 2, "0o": 8, "0d": 10, "0x": 16}[prefix]
    value = int(digits, base)
    return -value if match.group("sign") == "-" else value
