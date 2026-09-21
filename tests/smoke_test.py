"""Run against an installed wheel or sdist, without an editable source tree."""

import asyncio
import subprocess
import tempfile
from importlib.metadata import version

from ctmodbus.app import ModbusApp


def main():
    """Verify installed metadata, CLI help, and isolated project startup.

    Run with an installed artifact, not an editable checkout. Assert package
    versions and expected commands; subprocess failures propagate. Temporary
    project storage is removed on exit. Return None after printing success.
    """
    assert version("ctmodbus").startswith("1.")
    assert version("ctui").startswith("1.")
    result = subprocess.run(
        ["ctmodbus", "--help"], check=True, capture_output=True, text=True
    )
    assert "read holding_registers" in result.stdout
    assert "profile connect" in result.stdout
    with tempfile.TemporaryDirectory() as directory:
        app = ModbusApp(data_dir=directory)
        status = asyncio.run(
            app.run_cli(["-c", "project", "-c", "configs show tcp-local"])
        )
        assert status == 0
    print("Installed distribution smoke test passed")


if __name__ == "__main__":
    main()
