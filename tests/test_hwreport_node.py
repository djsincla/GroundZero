"""The Node.js gz-hwreport must report exactly what the Python collector does (same recorded R740xd)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from groundzero.inventory.collect import collect_inventory
from groundzero.redfish.capture import load_recording, replay_transport
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.storage import read_storage_layout

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "node" / "gz-hwreport.mjs"
R740XD = ROOT / "tests" / "fixtures" / "dell-r740xd"
# Only in the Python inventory: what GroundZero's own tasks need, not a hardware report.
PYTHON_ONLY = {("inventory", "capabilities"), ("inventory", "bmc", "license")}

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def _python() -> dict[str, Any]:
    async def read() -> dict[str, Any]:
        async with RedfishClient(
            "198.51.100.11", "root", "x", transport=replay_transport(load_recording(R740XD))
        ) as c:
            identity, inventory = await collect_inventory(c)
            storage = await read_storage_layout(c, identity.system_path, dell=identity.vendor.value == "dell")
        return {
            "bmc": "198.51.100.11",
            "inventory": inventory.model_dump(mode="json"),
            "storage": storage.model_dump(mode="json"),
        }

    return asyncio.run(read())


def _node(tmp_path: Path) -> dict[str, Any]:
    run = subprocess.run(
        ["node", str(SCRIPT), "--replay", str(R740XD), "198.51.100.11", "-o", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    return dict(json.loads(next(tmp_path.glob("*.json")).read_text()))


def _diff(py: Any, js: Any, path: tuple[str, ...] = ()) -> list[str]:
    if path in PYTHON_ONLY or path[-1:] == ("collected_at",):
        return []
    if isinstance(py, dict) and isinstance(js, dict):
        out = [
            f"{'.'.join((*path, k))}: missing in Node"
            for k in py
            if k not in js and (*path, k) not in PYTHON_ONLY
        ]
        out += [f"{'.'.join((*path, k))}: only in Node" for k in js if k not in py]
        return out + [d for k in py if k in js for d in _diff(py[k], js[k], (*path, k))]
    if isinstance(py, list) and isinstance(js, list):
        if len(py) != len(js):
            return [f"{'.'.join(path)}: {len(py)} items in Python, {len(js)} in Node"]
        return [d for i, (a, b) in enumerate(zip(py, js, strict=True)) for d in _diff(a, b, (*path, str(i)))]
    return [] if py == js else [f"{'.'.join(path)}: Python {py!r}, Node {js!r}"]


def test_node_matches_python_field_for_field(tmp_path: Path) -> None:
    differences = _diff(_python(), _node(tmp_path))
    assert differences == [], "\n".join(differences[:20])


def test_node_writes_the_pages_and_compares(tmp_path: Path) -> None:
    run = subprocess.run(
        ["node", str(SCRIPT), "--replay", str(R740XD), "198.51.100.11", "198.51.100.12", "-o", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0 and "2 of 2 servers read" in run.stdout
    page = next(tmp_path.glob("*.11_.html")).read_text()
    for section in ("system", "memory", "storage", "drives", "adapters", "pcie", "psu", "firmware"):
        assert f'data-section="{section}"' in page
    index = (tmp_path / "index.html").read_text()
    assert "No differences" in index and "Firmware: BIOS" in index


def test_node_reports_a_failure_and_needs_a_bmc(tmp_path: Path) -> None:
    run = subprocess.run(
        ["node", str(SCRIPT), "--replay", str(tmp_path / "none"), "198.51.100.13", "-o", str(tmp_path / "o")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 2 and "0 of 1 servers read" in run.stdout
    empty = subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert empty.returncode == 2 and "give at least one BMC address" in empty.stderr


def test_the_node_version_matches_groundzero() -> None:
    from groundzero import __version__

    assert f'const VERSION = "{__version__}";' in SCRIPT.read_text()  # bump it with pyproject.toml


def test_the_readme_covers_every_option() -> None:
    import re

    readme = (ROOT / "node" / "README.md").read_text()
    shown = subprocess.run(["node", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60).stdout
    options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+|-[a-z])\b", shown))
    assert options and not [o for o in sorted(options) if f"`{o}" not in readme and f" {o}" not in readme]
    assert "GZ_BMC_PASSWORD" in readme and "GZ_BMC_USERNAME" in readme
