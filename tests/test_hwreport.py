"""gz-hwreport: a hardware report straight from BMCs (replayed from the R740xd recording)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundzero.hwreport import main

R740XD = Path(__file__).parent / "fixtures" / "dell-r740xd"


def test_one_server_gets_a_page_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--replay", str(R740XD), "198.51.100.11", "-o", str(tmp_path)]) == 0
    page = next(tmp_path.glob("*.html")).read_text()
    for section in ("system", "memory", "storage", "drives", "adapters", "pcie", "psu", "firmware"):
        assert f'data-section="{section}"' in page
    assert (
        "PowerEdge R740xd" in page and "Integrated Dell Remote Access Controller" in page and "2000 W" in page
    )
    assert (
        "<script" not in page and "http" not in page.split("<footer>")[0]
    )  # self-contained, nothing fetched
    data = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert data["bmc"] == "198.51.100.11" and len(data["inventory"]["firmware"]) == 33
    assert data["storage"]["controllers"]
    assert not (tmp_path / "index.html").exists()  # one server: no comparison page
    assert "1 of 1 servers read" in capsys.readouterr().out


def test_several_servers_are_compared_and_a_failure_is_reported(tmp_path: Path) -> None:
    hosts = tmp_path / "bmcs.txt"
    hosts.write_text("198.51.100.11\n198.51.100.12 admin  # second\n\n")
    assert main(["--replay", str(R740XD), "-f", str(hosts), "-o", str(tmp_path / "out")]) == 0
    index = (tmp_path / "out" / "index.html").read_text()
    assert "2 of 2 servers read" in index and "No differences" in index and "BIOS" in index

    code = main(
        ["--replay", str(tmp_path / "missing"), "198.51.100.13", "198.51.100.14", "-o", str(tmp_path / "bad")]
    )
    assert code == 2
    index = (tmp_path / "bad" / "index.html").read_text()
    assert "0 of 2 servers read" in index and "Couldn" in index


def test_it_needs_a_bmc(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([])
    assert "give at least one BMC address" in capsys.readouterr().err
