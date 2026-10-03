"""Browser tests: drive the real web UI (Chromium via Playwright) against the simulated R740xd."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .harness import GroundZero

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isofactory import make_stock_iso

pytestmark = [pytest.mark.functional, pytest.mark.browser]

ISO_NAME = "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso"
CONFIRM = 'Type "install esxi1" to confirm'


def _open(page: Page, gz: GroundZero, path: str = "") -> None:
    token = gz.cli("token", "show").stdout.strip()
    page.goto(f"{gz.url}/#token={token}")
    expect(page.get_by_role("heading", name="Hosts", exact=True)).to_be_visible()
    assert "token=" not in page.url  # the token is removed from the address bar
    if path:
        page.goto(f"{gz.url}/#{path}")


def _add_host(page: Page, name: str = "esxi1") -> None:
    page.get_by_role("button", name="Add host").click()
    page.get_by_label("BMC address").fill("198.51.100.11")
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("BMC password").fill("simulated")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator(f'tr[data-host="{name}"]')).to_be_visible()


def _stock_iso(gz: GroundZero) -> Path:
    return make_stock_iso(gz.home / "isos" / ISO_NAME)


def _host_with_os(gz: GroundZero) -> None:
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("os", "set", "esxi1", "--address", "192.0.2.101").code == 0


def _tab(page: Page, name: str) -> None:
    page.get_by_role("navigation", name="Host sections").get_by_role("link", name=name).click()


def _main_nav(page: Page, name: str) -> None:
    page.get_by_role("navigation", name="Main").get_by_role("link", name=name, exact=True).click()


# ── shell ──
def test_sidebar_persists_on_every_page_including_api(page: Page, simulated_r740xd: GroundZero) -> None:
    """Regression (user report): the menu disappeared when opening the API page."""
    _open(page, simulated_r740xd)
    sidebar = page.get_by_role("navigation", name="Main")
    pages = [("Jobs", "Jobs"), ("Config sets", "Config sets"), ("ISOs", "ISO repository"),
             ("API", "API"), ("Info", "Info"), ("Hosts", "Hosts")]  # fmt: skip
    for link, heading in pages:
        _main_nav(page, link)
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(sidebar).to_be_visible()
        expect(sidebar.locator("a.active")).to_have_text(link)
        if link == "API":
            docs = page.frame_locator("iframe.api-frame")
            expect(docs.get_by_text("/api/v1/hosts").first).to_be_visible()
            expect(docs.locator(".information-container")).to_be_hidden()  # no second header inside the app
            expect(docs.get_by_role("button", name="Authorize")).to_be_hidden()  # uses the UI session
            # Regression (user report): "Try it out" came first, and the locks had no way to sign in.
            hosts_op = docs.locator("#operations-hosts-list_hosts_api_v1_hosts_get")
            hosts_op.locator(".opblock-summary").click()
            expect(hosts_op.get_by_role("button", name="Try it out")).to_have_count(0)
            hosts_op.get_by_role("button", name="Execute").click()
            expect(hosts_op.locator(".live-responses-table tbody .response-col_status")).to_have_text("200")


def test_theme_toggle_switches_and_persists(page: Page, simulated_r740xd: GroundZero) -> None:
    _open(page, simulated_r740xd)
    html = page.locator("html")
    page.get_by_role("button", name="Dark").click()
    expect(html).to_have_attribute("data-theme", "dark")
    dark_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.reload()
    expect(html).to_have_attribute("data-theme", "dark")  # remembered across reloads
    expect(page.get_by_role("button", name="Dark")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Light").click()
    expect(html).to_have_attribute("data-theme", "light")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != dark_bg
    page.get_by_role("button", name="System").click()
    assert page.evaluate("document.documentElement.dataset.theme") is None


def test_phone_width_has_a_menu_and_no_horizontal_scroll(page: Page, simulated_r740xd: GroundZero) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, simulated_r740xd)
    _add_host(page)
    sidebar = page.get_by_role("navigation", name="Main")
    expect(sidebar).not_to_be_in_viewport()
    page.get_by_role("button", name="Open menu").click()
    expect(sidebar).to_be_in_viewport()
    sidebar.get_by_role("link", name="Config sets").click()
    expect(page.get_by_role("heading", name="Config sets", exact=True)).to_be_visible()
    expect(sidebar).not_to_be_in_viewport()  # navigating closes the menu
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_no_token_shows_sign_in(page: Page, simulated_r740xd: GroundZero) -> None:
    page.goto(simulated_r740xd.url + "/")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    expect(page.get_by_role("navigation", name="Main")).to_be_hidden()
    page.get_by_label("API token").fill("wrong-token")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()  # rejected, still signed out


# ── hosts ──
def test_sign_in_add_host_and_preflight(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _open(page, gz)
    expect(page.get_by_text("No hosts yet")).to_be_visible()
    expect(page.get_by_text("simulation mode")).to_be_visible()
    _add_host(page)
    expect(page.locator(".toast").first).to_contain_text("Added esxi1")

    page.get_by_role("link", name="esxi1").click()
    _tab(page, "Preflight")
    page.get_by_role("button", name="Run preflight").click()
    expect(page.locator("#drawer")).to_contain_text("Preflight")  # live progress in the job drawer
    panel = page.locator('[data-panel="preflight"]')
    expect(panel.locator('[data-status="warn"]').first).to_be_visible(timeout=20_000)
    expect(panel.locator('tr[data-check="cpu.generation"]')).to_contain_text("Skylake-SP")
    expect(panel).to_contain_text("12 passed, 1 warnings, 0 failed, 0 unknown")

    _tab(page, "Overview")
    expect(page.locator('[data-card="preflight"]')).to_contain_text("12 passed, 1 warnings, 0 failed")
    _main_nav(page, "Hosts")
    expect(page.locator('tr[data-host="esxi1"]')).to_contain_text("PowerEdge R740xd")


def test_read_esxi_network(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _open(page, gz)
    _add_host(page)
    page.get_by_role("link", name="esxi1").click()
    _tab(page, "Networking")
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


def test_untrusted_strings_render_as_text(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    evil = '<img src=x onerror="document.body.dataset.pwned=1">'
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", evil).code == 0
    _open(page, gz)
    expect(page.get_by_role("link", name=evil)).to_be_visible()  # shown literally
    page.get_by_role("link", name=evil).click()
    expect(page.get_by_role("heading", name=evil)).to_be_visible()
    page.goto(f"{gz.url}/#/config-sets/new")
    page.get_by_label("Name").fill(evil)
    for label, value in [("Netmask", "255.255.255.0"), ("Gateway", "192.0.2.1"), ("DNS servers", "8.8.8.8")]:
        page.get_by_label(label).fill(value)
    page.get_by_role("button", name="Create").click()
    expect(page.get_by_role("link", name=evil)).to_be_visible()  # back on the list
    page.get_by_role("link", name=evil).click()
    expect(page.get_by_role("heading", name=evil)).to_be_visible()
    assert page.locator("main img").count() == 0
    assert page.evaluate("document.body.dataset.pwned") is None


# ── config sets and ISOs ──
def test_config_set_form_is_generated_and_shows_field_errors(
    page: Page, simulated_r740xd: GroundZero
) -> None:
    _open(page, simulated_r740xd, "/config-sets")
    page.get_by_role("link", name="New config set").first.click()
    page.get_by_label("Name").fill("lab-esxi")
    page.get_by_label("Netmask").fill("255.255.255.0")
    page.get_by_label("Gateway").fill("not-an-ip")
    page.get_by_label("DNS servers").fill("8.8.8.8, 1.1.1.1")
    page.get_by_label("Management VLAN").fill("100")
    page.get_by_label("Extra uplinks", exact=True).fill("vmnic1")
    page.get_by_label("Rule").select_option("first-match")  # nested model (DiskRule)
    page.get_by_label("CPU override").select_option("on")
    page.get_by_label("Root password").fill("S3cret-root!")
    page.get_by_role("button", name="Create").click()

    # The API's 422 errors land on the right fields, including the nested disk rule
    expect(page.locator('[data-field="gateway"]')).to_have_class(re.compile("invalid"))
    expect(page.locator('[data-field="install_disk"]')).to_have_class(re.compile("invalid"))
    expect(page.locator('[data-field="install_disk"] > .field-error')).to_contain_text("needs a value")
    page.get_by_label("Gateway").fill("192.0.2.1")
    page.get_by_label("Match / device").fill("DELLBOSS")
    page.get_by_role("button", name="Create").click()

    row = page.locator('tr[data-config-set="lab-esxi"]')  # saving returns to the list
    expect(row).to_contain_text("stored")
    row.get_by_role("link", name="lab-esxi").click()
    expect(page.get_by_role("heading", name="lab-esxi")).to_be_visible()
    expect(page.get_by_label("Management VLAN")).to_have_value("100")
    expect(page.get_by_label("Root password")).to_have_value("")  # never sent back
    expect(page.get_by_label("Root password")).to_have_attribute(
        "placeholder", re.compile("leave blank to keep")
    )
    assert "S3cret-root!" not in page.content()

    page.get_by_label("Management VLAN").fill("200")  # editing also returns to the list
    page.get_by_role("button", name="Save").click()
    expect(row).to_be_visible()
    expect(page.locator(".toast").last).to_contain_text("Saved lab-esxi")


def test_iso_repository_page_lists_and_rescans(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _open(page, gz, "/isos")
    expect(page.get_by_text("No ISOs found")).to_be_visible()
    _stock_iso(gz)
    page.get_by_role("button", name="Rescan folder").click()
    row = page.locator(f'tr[data-iso="{ISO_NAME}"]')
    expect(row).to_contain_text("9.1.1")
    expect(row).to_contain_text("25714478")
    expect(page.locator(".toast").first).to_contain_text("Found 1 image")


def test_capture_from_a_host_creates_a_config_set(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _host_with_os(gz)
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()
    _tab(page, "Networking")
    page.get_by_role("button", name="Capture config set…").click()
    page.get_by_label("Config set name").fill("from-esxi1")
    page.get_by_role("button", name="Capture", exact=True).click()
    expect(page.get_by_role("heading", name="from-esxi1")).to_be_visible(timeout=20_000)  # opens the new set
    expect(page.get_by_label("Management VLAN")).to_have_value("100")
    expect(page.get_by_label("Extra uplinks", exact=True)).to_have_value("vmnic1")
    expect(page.get_by_label("Rule")).to_have_value("current-boot-disk")


# ── deploy wizard ──
def test_deploy_with_a_config_set_previews_then_installs(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _stock_iso(gz)
    _host_with_os(gz)
    assert gz.cli("config", "capture", "esxi1", "--name", "lab-esxi", timeout=60).code == 0
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()
    page.get_by_role("link", name="Deploy OS…").click()

    expect(page.locator(f'[data-iso="{ISO_NAME}"] input')).to_be_checked()
    expect(page.get_by_label("Config set")).not_to_have_value("")  # the set, not "keep current settings"
    expect(page.get_by_label("Hostname")).to_have_value("esxi1")  # this server's stored values
    expect(page.get_by_label("Management IP")).to_have_value(re.compile(r"^\d+\.\d+\.\d+\.\d+$"))

    start = page.get_by_role("button", name="Start install")
    page.get_by_label(CONFIRM).fill("install esxi1")
    expect(start).to_be_disabled()  # the preview comes first

    page.get_by_label("Management IP").fill("999.1.1.1")
    page.get_by_role("button", name="Preview kickstart").click()
    expect(page.locator('[data-field="ip"]')).to_have_class(re.compile("invalid"))
    page.get_by_label("Management IP").fill("192.0.2.101")
    page.get_by_role("button", name="Preview kickstart").click()
    kickstart = page.locator('[data-role="kickstart"]')
    expect(kickstart).to_contain_text("--vlanid=100")
    expect(kickstart).to_contain_text("--hostname=esxi1")
    expect(kickstart).to_contain_text("$6$<hidden>")

    page.get_by_label(CONFIRM).fill("install esxi")
    expect(start).to_be_disabled()
    page.get_by_label(CONFIRM).fill("install esxi1")
    expect(start).to_be_enabled()
    start.click()

    expect(page.get_by_role("heading", name="Running")).to_be_visible()
    install = page.locator('[data-panel="install"]')
    expect(install.locator('[data-status="pass"]').first).to_be_visible(timeout=60_000)
    expect(install.locator('[data-role="install-summary"]')).to_contain_text(
        "Installed ESXi 9.1.1 build 25714478 (was 24957456) and validated"
    )


def test_deploy_keeping_current_settings_needs_exact_phrase(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _stock_iso(gz)
    _host_with_os(gz)
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()
    page.get_by_role("link", name="Deploy OS…").click()
    expect(page.get_by_label("Config set")).to_have_value("")  # no sets yet: keep current settings
    expect(page.get_by_role("button", name="Preview kickstart")).to_be_hidden()
    expect(page.get_by_label("Hostname")).to_be_hidden()
    start = page.get_by_role("button", name="Start install")
    page.get_by_label(CONFIRM).fill("install esxi")
    expect(start).to_be_disabled()
    page.get_by_label(CONFIRM).fill("install esxi1")
    expect(start).to_be_enabled()
    start.click()
    install = page.locator('[data-panel="install"]')
    expect(install.locator('[data-role="install-summary"]')).to_contain_text("and validated", timeout=60_000)
    expect(install).to_contain_text("datastores")


def test_failed_install_is_never_shown_as_installed(
    page: Page, simulated_r740xd_ignoring_boot_once: GroundZero
) -> None:
    """Regression (user report): a failed attempt's target version read like the installed version."""
    gz = simulated_r740xd_ignoring_boot_once
    iso = _stock_iso(gz)
    _host_with_os(gz)
    assert gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi1", timeout=180).code == 1
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()
    _tab(page, "Install")
    summary = page.locator('[data-panel="install"] [data-role="install-summary"]')
    expect(summary).to_contain_text("did not complete. Nothing was installed")
    expect(summary).to_contain_text("still on build 24957456")
    expect(summary).to_contain_text("instead of the installer")  # the job's own error message
    expect(summary).not_to_contain_text("Installed ESXi")
    _tab(page, "Overview")
    expect(page.locator('[data-card="os"]')).not_to_contain_text("Installed ESXi")


def test_info_page_shows_ipsec_block_and_allow_for_macos_and_windows(
    page: Page, simulated_r740xd: GroundZero
) -> None:
    _open(page, simulated_r740xd)
    _main_nav(page, "Info")
    expect(page.get_by_role("heading", name="VPN: block or allow GlobalProtect IPsec")).to_be_visible()
    mac, win = page.locator('[data-platform="macos"]'), page.locator('[data-platform="windows"]')
    expect(mac).to_contain_text("pfctl -a com.apple/250.groundzero -f -")  # block
    expect(mac).to_contain_text("pfctl -a com.apple/250.groundzero -F rules")  # allow
    expect(win).to_contain_text("New-NetFirewallRule")
    expect(win).to_contain_text("-Protocol UDP -RemotePort 4501 -Action Block")
    expect(win).to_contain_text("Remove-NetFirewallRule")
    expect(page.get_by_role("navigation", name="Main").locator("a.active")).to_have_text("Info")
    page.reload()  # deep link survives a reload
    expect(page.get_by_role("heading", name="Info", exact=True)).to_be_visible()


def test_build_a_config_set_from_a_running_server(page: Page, simulated_r740xd: GroundZero) -> None:
    """From the Config sets page; asks for OS credentials when GroundZero has none for that server."""
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    _open(page, gz, "/config-sets")
    page.get_by_role("button", name="From a running server…").first.click()
    expect(page.get_by_label("Config set name")).to_have_value("esxi1-captured")
    page.get_by_label("OS management address").fill("192.0.2.101")
    page.get_by_label("OS password").fill("simulated")
    page.get_by_role("button", name="Capture", exact=True).click()
    expect(page.get_by_role("heading", name="esxi1-captured")).to_be_visible(timeout=20_000)
    expect(page.get_by_label("Management VLAN")).to_have_value("100")

    # Second time round the saved OS access is reused, and a duplicate name is reported in the dialog
    _main_nav(page, "Config sets")
    page.get_by_role("button", name="From a running server…").first.click()
    expect(page.get_by_text("Reads 192.0.2.101 as root")).to_be_visible()
    expect(page.get_by_label("OS password")).to_be_hidden()
    page.get_by_role("button", name="Capture", exact=True).click()
    expect(page.locator("dialog")).to_contain_text("already exists")


# ── pipeline ──
def test_pipeline_guides_through_the_next_steps(page: Page, simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()  # the Pipeline tab is the default
    nxt = page.locator('[data-role="next-step"]')
    expect(nxt).to_contain_text("Holodeck preflight")
    expect(page.locator('[data-task="holodeck.router"]')).to_have_attribute("data-state", "planned")

    nxt.get_by_role("button", name="Holodeck preflight").click()
    drawer = page.locator("#drawer")
    expect(drawer.locator('[data-step="evaluate"]')).to_have_attribute(
        "data-status", "succeeded", timeout=20_000
    )
    expect(drawer.locator('[data-step="collect"]')).to_have_attribute("data-status", "succeeded")
    with page.expect_download() as download:
        drawer.get_by_role("button", name="Download diagnostics").click()
    bundle = json.loads(Path(download.value.path()).read_text())
    assert bundle["job"]["task"] == "preflight" and bundle["bmc_identity"]["vendor"] == "dell"
    assert any(e["event"] == "redfish" and e.get("status") == 200 for e in bundle["events"])

    expect(page.locator('[data-task="preflight"]')).to_have_attribute("data-state", "done")
    expect(page.locator('[data-task="preflight"] [data-role="output"]')).to_contain_text("12 passed")
    expect(nxt).to_contain_text("Deploy custom OS")  # no OS access yet
    expect(page.locator('[data-task="os.read"]')).to_contain_text("Needs: Set OS access")

    assert gz.cli("os", "set", "esxi1", "--address", "192.0.2.101").code == 0
    page.reload()
    expect(nxt).to_contain_text("Assess Holodeck readiness")  # it reads the OS itself
    page.locator('[data-task="os.read"]').get_by_role("button", name="Run").click()  # optional utility
    expect(page.locator('[data-task="os.read"]')).to_have_attribute("data-state", "done", timeout=20_000)
    expect(page.locator('[data-task="os.read"] [data-role="output"]')).to_contain_text("VMware ESXi")


def test_readiness_report_shows_checks_storage_and_planned_fixes(
    page: Page, simulated_r740xd: GroundZero
) -> None:
    gz = simulated_r740xd
    _host_with_os(gz)
    assert gz.cli("run", "esxi1", "preflight", timeout=120).code == 0
    _open(page, gz)
    page.get_by_role("link", name="esxi1").click()
    nxt = page.locator('[data-role="next-step"]')
    nxt.get_by_role("button", name="Assess Holodeck readiness").click()
    expect(page.locator('[data-task="host.assess"]')).to_have_attribute("data-state", "done", timeout=20_000)
    page.locator('[data-task="host.assess"]').get_by_role("link", name="View report").click()

    expect(page.locator('[data-panel="readiness"]')).to_contain_text("not ready")
    expect(page.locator('[data-role="storage"]')).to_contain_text("existing flash datastore localHolodeck")
    expect(page.locator('tr[data-check="network.mtu"]')).to_contain_text("vSwitch0: 1500")
    plan = page.locator('[data-panel="plan"]')
    expect(plan.locator('[data-action="set_mtu"]')).to_contain_text("Set vSwitch0 MTU to 9000")
    expect(plan.locator('[data-check="network.external"] input')).not_to_be_checked()  # optional fix
    expect(plan.locator('[data-action="set_mtu"] input')).to_be_checked()

    # Apply the fixes, including the optional external port group on VLAN 100
    plan.locator('[data-check="network.external"] input').check()
    plan.get_by_role("button", name="Apply selected fixes…").click()
    dialog = page.locator("dialog")
    expect(dialog).to_contain_text("Set vSwitch0 MTU to 9000")
    expect(dialog).to_contain_text("Create port group Holodeck-External (VLAN 100) on vSwitch0")
    dialog.get_by_role("button", name="Apply").click()
    drawer = page.locator("#drawer")
    expect(drawer.locator('[data-step="reassess"]')).to_have_attribute(
        "data-status", "succeeded", timeout=20_000
    )
    expect(drawer.locator('[data-step="network.mtu"]')).to_contain_text("MTU 1500 → MTU 9000")
    page.reload()
    expect(page.locator('tr[data-check="network.mtu"] [data-status="pass"]')).to_be_visible()

    # Then the jumbo-frame test; afterwards nothing is left to fix
    plan.locator('[data-action="verify_jumbo"]').get_by_role("button", name="Run test").click()
    expect(drawer.locator('[data-step="loop"]')).to_have_attribute("data-status", "succeeded", timeout=20_000)
    page.reload()
    expect(page.locator('[data-panel="readiness"]')).to_contain_text("ready")
    expect(page.locator('[data-panel="readiness"] [data-status="pass"]').first).to_have_text("ready")
    expect(plan).to_contain_text("Nothing to fix")
