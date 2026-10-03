"""Pump/tank emulator hooks; loaded from the adjacent device.toml definition."""


def on_write(device, tag, value):
    """Follow complete writes to pump_enabled with the simulated running status."""
    if tag == "pump_enabled":
        device.set("pump_running", bool(value))


def on_tick(device, elapsed_seconds):
    """Drain one unit per second while pumping; clamp at zero."""
    if device.get("pump_running"):
        level = device.get("tank_level")
        device.set("tank_level", max(0.0, level - elapsed_seconds))
