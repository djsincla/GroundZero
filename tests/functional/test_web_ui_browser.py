"""Browser tests: drive the real web UI (Chromium via Playwright) against the simulated R740xd."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .harness import GroundZero

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isofactory import make_stock_iso

pytestmark = [pytest.mark.functional, pytest.mark.browser]


def _open(page: Page, gz: GroundZero) -> None:
    token = gz.cli("token", "show").stdout.strip()
    page.goto(f"{gz.url}/#token={token}")
    expect(page.get_by_role("heading", name="Hosts")).to_be_visible()
    assert "token=" not in page.url  # the token is removed from the address bar


def _add_host(page: Page, name: str = "esxi1") -> None:
    page.get_by_role("button", name="Add host").click()
    page.get_by_label("BMC address").fill("198.51.100.11")
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("BMC password").fill("simulated")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator(f'tr[data-host="{name}"]')).to_be_visible()


def test_sign_in_add_host_and_preflight(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _open(page, gz)
    expect(page.get_by_text("No hosts yet")).to_be_visible()
    expect(page.get_by_text("simulation mode")).to_be_visible()
    _add_host(page)

    page.get_by_role("link", name="esxi1").click()
    page.get_by_role("button", name="Run preflight").click()
    panel = page.locator('[data-panel="preflight"]')
    expect(panel.locator('[data-status="warn"]').first).to_be_visible(timeout=20_000)
    expect(panel.locator('tr[data-check="cpu.generation"]')).to_contain_text("Skylake-SP")
    expect(panel).to_contain_text("12 passed, 1 warnings, 0 failed, 0 unknown")

    page.get_by_role("link", name="Hosts").click()
    expect(page.locator('tr[data-host="esxi1"]')).to_contain_text("PowerEdge R740xd")


def test_read_esxi_network(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _open(page, gz)
    _add_host(page)
    page.get_by_role("link", name="esxi1").click()
    page.get_by_role("button", name="Set OS access").click()
    page.get_by_label("Management address").fill("192.0.2.101")
    page.get_by_label("Password", exact=True).fill("simulated")
    page.get_by_role("button", name="Save").click()
    page.get_by_role("button", name="Read now").click()
    net = page.locator('[data-panel="network"]')
    expect(net).to_contain_text("Management Network", timeout=20_000)
    expect(net).to_contain_text("vmnic0, vmnic1")
    expect(net).to_contain_text("dwayneN4032 Te1/0/11")
    expect(net).to_contain_text("NTP none")


def test_install_needs_exact_phrase_then_shows_live_progress(
    page: Page, simulated_r740xd: GroundZero
) -> None:
    gz = simulated_r740xd
    iso = make_stock_iso(gz.home / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("os", "set", "esxi1", "--address", "192.0.2.101").code == 0
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()

    page.get_by_role("button", name="Reinstall ESXi…").click()
    page.get_by_label("Stock ESXi ISO").fill(str(iso))
    submit = page.get_by_role("button", name="Reinstall", exact=True)
    page.get_by_label('Type "install esxi1" to confirm').fill("install esxi")
    expect(submit).to_be_disabled()
    page.get_by_label('Type "install esxi1" to confirm').fill("install esxi1")
    expect(submit).to_be_enabled()
    submit.click()

    expect(page.get_by_role("heading", name="Running")).to_be_visible()
    install = page.locator('[data-panel="install"]')
    expect(install.locator('[data-status="pass"]').first).to_be_visible(timeout=60_000)
    expect(install.locator('[data-role="install-summary"]')).to_contain_text(
        "Installed ESXi 9.1.1 build 25714478 (was 24957456) and validated"
    )
    expect(install).to_contain_text("datastores")


def test_untrusted_strings_render_as_text(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    evil = '<img src=x onerror="document.body.dataset.pwned=1">'
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", evil).code == 0
    _open(page, gz)
    expect(page.get_by_role("link", name=evil)).to_be_visible()  # shown literally
    assert page.locator("main img").count() == 0
    assert page.evaluate("document.body.dataset.pwned") is None


def test_no_token_shows_sign_in(page: Page, simulated_r740xd: GroundZero) -> None:
    page.goto(simulated_r740xd.url + "/")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    page.get_by_label("API token").fill("wrong-token")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()  # rejected, still signed out


def test_failed_install_is_never_shown_as_installed(
    page: Page, simulated_r740xd_ignoring_boot_once: GroundZero
) -> None:
    """Regression (user report): a failed attempt's target version read like the installed version."""
    gz = simulated_r740xd_ignoring_boot_once
    iso = make_stock_iso(gz.home / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("os", "set", "esxi1", "--address", "192.0.2.101").code == 0
    assert gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi1", timeout=180).code == 1
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()
    summary = page.locator('[data-panel="install"] [data-role="install-summary"]')
    expect(summary).to_contain_text("did not complete. Nothing was installed")
    expect(summary).to_contain_text("still on build 24957456")
    expect(summary).to_contain_text("instead of the installer")  # the job's own error message
    expect(summary).not_to_contain_text("Installed ESXi")
