"""The web UI is served by the real server process (browser-level tests: test_web_ui_browser.py)."""

from __future__ import annotations

import httpx
import pytest

from .harness import GroundZero

pytestmark = pytest.mark.functional


def test_ui_assets_served_without_auth_and_data_still_protected(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    index = httpx.get(gz.url + "/")
    assert index.status_code == 200 and "<title>GroundZero</title>" in index.text
    assert index.headers["cache-control"] == "no-store"
    js = httpx.get(gz.url + "/ui/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js.text  # rendering goes through textContent only
    assert httpx.get(gz.url + "/ui/app.css").status_code == 200
    assert httpx.get(gz.url + "/api/v1/hosts").status_code == 401  # the UI shell is public, the data is not
