"""The project documents, issue forms and manual stay complete and link only to things that exist."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "docs" / "manual"
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
SCREENSHOT_URL = "https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/"
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_SHOT = re.compile(r"shot\(page, [^,]+, '([a-z-]+)'\)")


def _screens() -> set[str]:
    """Screenshot names the e2e screenshot specs write (and the wiki workflow publishes)."""
    names = set(re.findall(r"\['([a-z-]+)', '/", _read(ROOT / "frontend" / "e2e" / "screenshots.spec.ts")))
    for spec in (ROOT / "frontend" / "e2e").glob("screenshots*.spec.ts"):
        names |= set(_SHOT.findall(_read(spec)))
    return names


@pytest.mark.parametrize("name", ["bug.yml", "feature.yml", "router-support.yml"])
def test_issue_form_has_name_and_body(name: str) -> None:
    form = yaml.safe_load(_read(FORMS / name))
    assert form["name"]
    assert form["description"]
    assert isinstance(form["body"], list) and form["body"]


def test_router_support_form_asks_for_the_self_description() -> None:
    form = _read(FORMS / "router-support.yml")
    for wanted in ("ubus call system board", "/etc/board.json", "iw phy", "router-support"):
        assert wanted in form


def test_blank_issues_are_off() -> None:
    config = yaml.safe_load(_read(FORMS / "config.yml"))
    assert config["blank_issues_enabled"] is False
    assert config["contact_links"]


def test_readme_links_the_project_files() -> None:
    readme = _read(ROOT / "README.md")
    for target in ("ROADMAP.md", "CONTRIBUTING.md", "LICENSE"):
        assert f"]({target})" in readme, target
    assert SCREENSHOT_URL + "dashboard.png" in readme


def released_minors(changelog: str) -> list[str]:
    """The `x.y` of every released `## [x.y.z] - date` section, newest first, each once."""
    found = re.findall(r"^## \[(\d+\.\d+)\.\d+\] - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
    return list(dict.fromkeys(found))


def test_readme_describes_every_released_minor() -> None:
    """0.7.0 shipped with a README that stopped at v0.6: the opening note names the newest release and every
    release has its "What vX.Y adds" section."""
    readme = _read(ROOT / "README.md")
    minors = released_minors(_read(ROOT / "CHANGELOG.md"))
    assert {"0.1", "0.6", "0.7"} <= set(minors)
    assert f"> v{minors[0]} adds " in readme, minors[0]
    assert "## What v0.1 does" in readme
    missing = [m for m in minors if m != "0.1" and f"## What v{m} adds" not in readme]
    assert missing == []


def test_readme_screenshots_are_ones_e2e_writes() -> None:
    shown = {
        t.removeprefix(SCREENSHOT_URL).removesuffix(".png")
        for t in _LINK.findall(_read(ROOT / "README.md"))
        if t.startswith(SCREENSHOT_URL)
    }
    assert {"wifi", "rf-live", "luci-page"} <= shown
    assert shown <= _screens()


def test_every_sidebar_page_exists() -> None:
    pages = [t for t in _LINK.findall(_read(MANUAL / "_Sidebar.md")) if not t.startswith("http")]
    assert len(pages) >= 10
    for page in pages:
        assert (MANUAL / f"{page}.md").is_file(), page


def test_manual_links_and_screenshots_resolve() -> None:
    screens = _screens()
    assert {"dashboard", "settings", "terminal"} <= screens
    for page in MANUAL.glob("*.md"):
        for target in _LINK.findall(_read(page)):
            if target.startswith(SCREENSHOT_URL):
                name = target.removeprefix(SCREENSHOT_URL).removesuffix(".png")
                assert name in screens, (page.name, target)
            elif not target.startswith(("http", "#", "mailto:")):
                assert (MANUAL / f"{target.split('#')[0]}.md").is_file(), (page.name, target)


def test_changelog_has_the_release_section() -> None:
    changelog = _read(ROOT / "CHANGELOG.md")
    assert "## [Unreleased]" in changelog
    assert "## [0.1.0]" in changelog
    notes = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "release_notes.py"), "0.1.0"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Bench Guard" in notes.stdout


def test_roadmap_has_every_milestone() -> None:
    roadmap = _read(ROOT / "ROADMAP.md")
    for milestone in ("v0.1 Foundation", "v0.2", "v0.3", "v0.4", "v0.5", "v0.6", "v0.7", "v1.0", "1.x"):
        assert milestone in roadmap, milestone


# the GitHub milestones made for 1.x (the 1.x proposal's D11 and D12), one ROADMAP row each
ONE_X = (
    "v1.1 Leftovers, rate statistics and key rotation",
    "v1.2 Tool pages",
    "v1.3 LTE phase 2",
    "1.x (phase 2)",
)


def test_roadmap_and_the_spec_split_1_x_alike() -> None:
    roadmap = _read(ROOT / "ROADMAP.md")
    spec = _read(ROOT / "docs" / "superpowers" / "specs" / "2026-11-03-openwrt-gui-design.md")
    for row in ONE_X:
        assert f"| {row} |" in roadmap, row
        assert f"| {row} |" in spec, row


def test_agents_file_carries_the_bench_rules() -> None:
    agents = _read(ROOT / "AGENTS.md")
    assert "192.168.1.2" in agents
    assert "never type" in agents
    assert _read(ROOT / "CLAUDE.md").strip() == "See AGENTS.md."


def test_installer_test_covers_update_in_place() -> None:
    """v1.0d D7: an update over the latest release keeps the data folder and runs."""
    script = _read(ROOT / "tools" / "test_installer.ps1")
    for words in ("[string]$Previous", "/RELAUNCH=0", "the update keeps the data folder", "DisplayVersion"):
        assert words in script, words
    ci = _read(ROOT / ".github" / "workflows" / "ci.yml")
    assert "gh release download" in ci and "-Previous" in ci


def test_installer_update_check_hashes_the_whole_data_folder_by_name() -> None:
    """The v1.0d final review: only top-level files were hashed; a renamed file kept the same hash list."""
    script = _read(ROOT / "tools" / "test_installer.ps1")
    assert "function Snapshot" in script and "-Recurse" in script
    assert "$before = Snapshot $DataU" in script and "$after = Snapshot $DataU" in script


def test_repo_files_exist() -> None:
    for name in ("SECURITY.md", "CODE_OF_CONDUCT.md", ".github/PULL_REQUEST_TEMPLATE.md"):
        assert (ROOT / name).is_file(), name


def test_home_lists_every_sidebar_page() -> None:
    """v1.0a1 D8: the manual's home page links every page the sidebar has."""
    sidebar = {t for t in _LINK.findall(_read(MANUAL / "_Sidebar.md")) if not t.startswith("http")}
    home = set(_LINK.findall(_read(MANUAL / "Home.md")))
    assert sidebar - {"Home"} <= home, sorted(sidebar - home)
    assert "covers v0.4" not in _read(MANUAL / "Home.md")


def test_v1_0a2_pages_are_documented() -> None:
    system = _read(MANUAL / "System.md")
    wanted = ("## Plugins", "Configure in LuCI", "## Mount points", "block-mount", "Generate", "extroot")
    for text in wanted:
        assert text in system, text
    firewall = _read(MANUAL / "Firewall.md")
    assert "## Legacy iptables" in firewall and "filter table" in firewall
    assert "AP4" not in _read(MANUAL / "LuCI-pages.md")  # the simulator's router is not the user's


def test_v1_0a3_vlan_editor_is_documented() -> None:
    ports = _read(MANUAL / "Ports-and-VLANs.md")
    assert "## VLANs on a DSA router" in ports
    for words in ("60 s rollback", "may carry this app's SSH", "2 minutes", "power-cycle", "own-port lock"):
        assert words in ports, words
    assert "## A router that does not come back after a rollback" in _read(MANUAL / "Troubleshooting.md")
    assert "Switch/VLAN config opens the Ports screen" in _read(MANUAL / "LuCI-pages.md")
    released = _read(ROOT / "CHANGELOG.md").split("## [0.8.0]", 1)[1].split("## [", 1)[0]
    assert "bridge VLAN" in released  # shipped in 0.8.0
    assert "AP5" not in ports  # the simulator's router is not the user's


def test_no_manual_page_answers_for_v0_1() -> None:
    assert "Not in v0.1" not in _read(MANUAL / "FAQ.md")


_INTERNAL = re.compile(
    r"open item|\(O\d{1,2}\)|\bO\d{1,2}\b|txctl|AP2 recording|not built yet|not offered yet"
)
_TS_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _user_pages() -> dict[str, str]:
    return {p.stem: _read(p) for p in MANUAL.glob("*.md")}


def _python_strings(path: Path) -> list[str]:
    """String constants in a module, docstrings left out (they are for developers)."""
    tree = ast.parse(_read(path))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def test_manual_names_no_open_items_or_bench_sessions() -> None:
    """v1.0d D2: open-item numbers and the bench's own sessions mean nothing to a user."""
    found = [(page, m.group(0)) for page, text in _user_pages().items() for m in _INTERNAL.finditer(text)]
    assert found == []


def test_the_app_shows_no_open_items_or_bench_sessions() -> None:
    found = [
        (p.name, s)
        for p in (ROOT / "src" / "openwrtgui").rglob("*.py")
        for s in _python_strings(p)
        if _INTERNAL.search(s)
    ]
    for p in (ROOT / "frontend" / "src").rglob("*.ts*"):
        if ".test." in p.name or p.parent.name == "testing" or p.name == "schema.ts":
            continue
        found += [(p.name, m.group(0)) for m in _INTERNAL.finditer(_TS_COMMENT.sub("", _read(p)))]
    assert found == []


def _sections(text: str) -> dict[str, str]:
    """`## Heading` -> its body, for checks that must look in the right place."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def test_troubleshooting_covers_the_common_failures() -> None:
    sections = _sections(_read(MANUAL / "Troubleshooting.md"))
    wanted = {
        "The router is busy": "is busy",
        "An update does not download or install": "SHA256SUMS",
        # the app's own messages, quoted: a word like "power" is in any text (the v1.0d final review)
        "A reboot or a flash does not come back": "did not come back within 10\n  minutes",
        "A LuCI page does not open": "No LuCI page",
        "Wireshark does not start": "Wireshark is not installed on this PC",
        "The LTE modem has no address": "no address yet: waiting for the carrier's DHCP",
        '"This screen hit an error"': "Unexpected error in OpenWrtGUI",
    }
    missing = [h for h, words in wanted.items() if words not in sections.get(h, "")]
    assert missing == []


def test_troubleshooting_names_the_capture_buttons_as_they_read() -> None:
    """The v1.0d final review: the page bolded "to Wireshark", which no button says."""
    body = _sections(_read(MANUAL / "Troubleshooting.md"))["Wireshark does not start"]
    assert "**Live in Wireshark**" in body and "**Save .pcap**" in body
    assert "**to Wireshark**" not in body


def test_faq_answers_the_common_questions() -> None:
    """The FAQ asks each question as a bold line (v1.0d)."""
    faq = _read(MANUAL / "FAQ.md")
    for question in ("rollback", "busy", "LTE", "LuCI", "Wireshark"):
        assert re.search(rf"^\*\*[^*\n]*{question}[^*\n]*\*\*$", faq, re.MULTILINE | re.IGNORECASE), question


GUARDED = {  # each module that calls require_clear() -> the words "What is refused" uses for it (v1.0d)
    "discovery/service.py": "Discovery",
    "flash/service.py": "flash",
    "guard/writes.py": "Apply",
    "lte/service.py": "LTE",
    "lte/modem.py": "Enter PIN, Delete SMS, Send SMS, Send USSD",
    "lte/recover.py": "Recover",
    "onboard/rotate.py": "Rotate key",
    "net/apply.py": "rollback",
    "net/service.py": "Network",
    "rf/frames_service.py": "frame analysis",
    "rf/scan_service.py": "channel scan",
    "system/access_service.py": "router password",
    "system/jobs.py": "reboot",
    "system/service.py": "diagnostics",
    "tools/service.py": "Traffic generator",
    "tools/station_service.py": "Station management",
    "tools/sessions.py": "Throughput",
    "wifi/step_service.py": "step-through",
}


def test_bench_guard_names_every_guarded_area() -> None:
    src = ROOT / "src" / "openwrtgui"
    calling = {p.relative_to(src).as_posix() for p in src.rglob("*.py") if "require_clear()" in _read(p)}
    assert calling == set(GUARDED), sorted(calling ^ set(GUARDED))
    refused = _sections(_read(MANUAL / "Bench-Guard.md"))["What is refused"]
    assert sorted(w for w in set(GUARDED.values()) if w not in refused) == []


def _section(page: str, heading: str) -> str:
    """One `## ` section of a manual page, whitespace flattened: a quoted message may wrap across lines."""
    return " ".join(_sections(_read(MANUAL / f"{page}.md")).get(heading, "").split())


def test_v1_0c_behaviour_is_documented() -> None:
    """Each line is looked for in the section that owns the behaviour, so a stray mention elsewhere on the
    page does not count (the final review: "this PC" already matched the Faults page's intro)."""
    wanted = {
        ("LTE-modem", "Live signal"): ("reconnecting (attempt",),
        ("RF-live", "Charts"): ("reconnecting (attempt",),
        ("RF-live", "Record to CSV"): ("Recording stopped when the connection was lost",),
        ("System", "Live load, bandwidth and connections"): ("reconnecting (attempt",),
        ("Faults-and-capture", "Capture"): ("Wireshark fell behind",),
        ("Faults-and-capture", "Block flows"): ("has no conntrack",),
        ("Faults-and-capture", "Target"): ("this PC is not offered as one",),
        ("Dashboard", "Router overview"): ("Remove from the app",),
        ("Discovery", "Flash this image"): ("**Flash** stays grey while a run is live",),
        ("Ports-and-VLANs", "VLANs on a DSA router"): ("greyed", "LuCI lists the entries in its own order"),
    }
    missing = [(where, w) for where, words in wanted.items() for w in words if w not in _section(*where)]
    assert missing == []


def test_key_rotation_is_documented() -> None:
    """v1.1b D8: Settings explains Rotate key and Retry; Files and data names the rotation's files."""
    key = _section("Settings", "App SSH key")
    for words in ("**Rotate key**", "**Retry**", "does not answer", "harness run"):
        assert words in key, words
    # final review F1 and F3: the last check before the old key goes, and an old key kept in another line
    for words in ("logs in to every moved router with the new key again", "still accepts the old key"):
        assert words in key, words
    files = _read(MANUAL / "Files-and-data.md")
    assert "id_ed25519.next" in files and "rotation.json" in files


def test_v1_1b_is_in_the_changelog() -> None:
    released = _read(ROOT / "CHANGELOG.md").split("## [1.1.0]", 1)[1].split("\n## [", 1)[0]
    assert "Which rates reach the station" in released and "**Rotate key**" in released


def test_v1_2_is_in_the_changelog() -> None:
    changelog = _read(ROOT / "CHANGELOG.md")
    assert "\n## [1.2.0] - " in changelog  # the dated heading release_notes.py reads
    released = changelog.split("\n## [1.2.0] - ", 1)[1].split("\n## [", 1)[0]
    for words in (
        "**Capabilities**",
        "Port statistics",
        "Connections",
        "SIP ALG",
        "Throughput",
        "Traffic generator",
        "Station management",
        # PR #98 review: reads pause while the window is not in front (the manual says so), and the neighbour
        # report is the AP's list of nearby access points, not a station's answer
        "while the tab is open and the window is in front",
        "list of nearby access points",
    ):
        assert words in released, words


def test_recover_documents_the_setup_wait() -> None:
    """#93 (v1.3a): each Recover step waits for an LTE setup to finish, or is skipped; the factory reset is
    covered by Recover (C8)."""
    recover = _section("LTE-modem", "Recovering the modem")
    for words in ("no LTE setup runs", "20 seconds", "skipped"):
        assert words in recover, words
    changelog = _read(ROOT / "CHANGELOG.md")
    release = changelog.split("## [1.3.0]", 1)[1].split("\n## [", 1)[0]
    # the detailed Fixed entry, not the release's summary line, which names Recover and a setup too (PR #110)
    fixed = " ".join(release.split("### Fixed", 1)[1].split("\n### ", 1)[0].split())
    for words in ("LTE Recover waits for an LTE setup in progress before each step", "skips", "(#93)"):
        assert words in fixed, words
    roadmap = _read(ROOT / "ROADMAP.md")
    assert "factory reset (once its command is found)" not in roadmap
    assert "the modem's factory reset and its mode names" not in roadmap


def test_v1_3_is_in_the_changelog() -> None:
    released = _read(ROOT / "CHANGELOG.md").split("## [1.3.0]", 1)[1].split("\n## [", 1)[0]
    for words in (
        "**SIM PIN**",
        "**SMS**",
        "**USSD**",
        "LTE Recover waits",
        "router commands are no longer written to the app log",
    ):
        assert words in released, words


def test_rates_are_documented_as_read() -> None:
    """v1.1b D7: the rates card is read every 5 s while it is open; the manual no longer says it is not."""
    rates = _section("RF-live", "Which rates reach the station")
    assert "not read in this version" not in rates
    assert "**Show rates**" in rates and "every 5 seconds" in rates


def test_flash_recovery_matches_the_app() -> None:
    """The final review: the manual said to power-cycle a flash after 5 minutes, while the app waits 10 and
    says not to power off a router that may still be writing flash."""
    back = _section("Troubleshooting", "A reboot or a flash does not come back")
    assert "It may still be writing flash: do not power it off" in back
    assert "Once 5 minutes have passed" not in back
    assert "a flash that takes longer than 5 minutes" not in _section("Troubleshooting", "The router is busy")


def test_not_verified_names_every_cause() -> None:
    """The final review: "Applied, not verified" also follows a failed check (CheckList.tsx names the
    checks), not only a lost connection or a run."""
    for page, heading in (("How-changes-work", "Proof on air"), ("Wi-Fi", "Apply and proof on air")):
        assert "a check fails" in _section(page, heading), page


def test_faq_busy_answer_matches_the_jobs() -> None:
    """The final review: only a reboot, a restore and a reset share one slot; a flash refuses a second flash
    and an LTE action a second LTE action."""
    faq = " ".join(_read(MANUAL / "FAQ.md").split())
    answer = faq.split("**Why does a screen say the router is busy?**", 1)[1].split("**", 1)[0]
    assert "a second flash" in answer and "a second LTE action" in answer


SCREEN_PAGES = (
    "Dashboard",
    "First-router",
    "Discovery",
    "Wi-Fi",
    "RF-live",
    "Network-and-DHCP",
    "LTE-modem",
    "Ports-and-VLANs",
    "Firewall",
    "Faults-and-capture",
    "System",
    "Tools",
    "LuCI-pages",
    "Bench-Guard",
    "Terminal-and-audit-log",
    "Settings",
)


def _shown(text: str) -> set[str]:
    return {
        t.removeprefix(SCREENSHOT_URL).removesuffix(".png")
        for t in _LINK.findall(text)
        if t.startswith(SCREENSHOT_URL)
    }


def test_every_screen_page_shows_a_screenshot() -> None:
    assert [p for p in SCREEN_PAGES if not _shown(_read(MANUAL / f"{p}.md"))] == []


def test_every_screenshot_taken_is_used() -> None:
    used = _shown(_read(ROOT / "README.md"))
    for page in MANUAL.glob("*.md"):
        used |= _shown(_read(page))
    assert sorted(_screens() - used) == []
    assert {
        "step-through",
        "channel-analysis",
        "frame-analysis",
        "flash-dialog",
        "guard-banner",
    } <= _screens()


_ROW = re.compile(r"^\| `([^`]+)` \|", re.MULTILINE)


def test_v1_0d_pages_exist() -> None:
    sidebar = _read(MANUAL / "_Sidebar.md")
    wanted = {
        "How-changes-work": (
            "## Preview",
            "## Apply with rollback",
            "## Proof on air",
            "## Refused",
            "## Bench Guard",
        ),
        "Files-and-data": ("## The data folder", "## Documents", "## On a router", "## Moving or removing"),
        "Glossary": (
            "**App key**",
            "**Host key**",
            "**Rollback**",
            "**Proof on air**",
            "**Overlay**",
            "**Monitor interface**",
            "**netem**",
            "**DSA**",
            "**swconfig**",
            "**AT command**",
            "**Run**",
            "**Step-through**",
        ),
    }
    for page, parts in wanted.items():
        assert f"]({page})" in sidebar, page
        assert (MANUAL / f"{page}.md").is_file(), page
        text = _read(MANUAL / f"{page}.md")
        assert [p for p in parts if p not in text] == [], page


def test_files_and_data_matches_security() -> None:
    """v1.0d D6: the user page and the security policy list the same data folder."""
    security = set(_ROW.findall(_read(ROOT / "SECURITY.md")))
    files = (
        set(_ROW.findall(_read(MANUAL / "Files-and-data.md")))
        if (MANUAL / "Files-and-data.md").is_file()
        else set()
    )
    assert security and security == files, sorted(security ^ files)


_ISS_DELETES = re.compile(r"(?:DeleteFile|DelTree)\(Dir \+ '\\([^']+)'")


def test_uninstall_deletes_backups_and_the_manual_says_what() -> None:
    """2026-11-16 decision: uninstall's Yes also deletes backups\\ (password hashes, Wi-Fi keys). The manual's
    "Yes deletes" list is the installer's DeleteAppData list, scratch files aside."""
    iss = _read(ROOT / "installer" / "OpenWrtGUI.iss")
    deleted = {n for n in _ISS_DELETES.findall(iss) if not n.endswith((".tmp", ".bad", ".lock"))}
    assert "backups" in deleted
    yes = _section("Files-and-data", "Moving or removing").split("**Yes** deletes", 1)[1].split(" - ", 1)[0]
    documented = set(re.findall(r"`([a-z_.-]+)\\?`", yes))
    assert documented == deleted, sorted(documented ^ deleted)


def test_the_lte_page_explains_recover_and_saved_setups() -> None:
    """Spec 4.7: Recovering the modem names the five steps; Save good setup, Reconfigure and the AT warning
    are in their sections; Troubleshooting points to Recover."""
    sections = _sections(_read(MANUAL / "LTE-modem.md"))
    recovering = sections["Recovering the modem"]
    for rung in (
        "Put back the saved setup",
        "Reconnect",
        "Clear QMI state",
        "Turn off the modem's autoconnect",
        "Restart the modem",
    ):
        assert rung in recovering, rung
    assert "**Save good setup**" in sections["Settings"] and "**Reconfigure**" in sections["Settings"]
    assert "Use Recover instead" in sections["AT console"]
    assert "no packet-data handle" in sections["Status"]
    assert "Recover" in _section("Troubleshooting", "LTE does not connect")


def test_the_lte_page_explains_sim_sms_and_ussd() -> None:
    """v1.3b: the three sections follow Modem, say what each write waits for, and the CHANGELOG names them."""
    sections = _sections(_read(MANUAL / "LTE-modem.md"))
    for name in ("SIM PIN", "SMS", "USSD"):
        assert len(sections[name].split()) >= 30, name
    assert "last try" in sections["SIM PIN"] or "last tries" in sections["SIM PIN"]
    assert "during a harness run" in sections["SMS"] and "160" in sections["SMS"]
    assert "35 seconds" in sections["USSD"] and "AT console" in sections["USSD"]
    assert "menus" in sections["USSD"] and "closes the session" in sections["USSD"]
    assert "call barring" in sections["USSD"] and "`**` or `##` are refused" in sections["USSD"]  # P16
    order = [m for m in re.findall(r"^## (.+)$", _read(MANUAL / "LTE-modem.md"), flags=re.M)]
    assert order.index("Modem") < order.index("SIM PIN") < order.index("SMS") < order.index("USSD")
    unreleased = _read(ROOT / "CHANGELOG.md").split("## [1.3.0]", 1)[1].split("\n## [", 1)[0]
    added = unreleased.split("### Added", 1)[1].split("\n### ", 1)[0]
    for name in ("SIM PIN", "SMS", "USSD"):
        assert f"**{name}**" in added, name


def test_security_says_the_pin_is_briefly_on_the_router() -> None:
    security = _read(ROOT / "SECURITY.md")
    assert "command line" in security and "Enter PIN" in security


def _flat(text: str) -> str:
    return " ".join(text.split())


def _unreleased(kind: str) -> str:
    unreleased = _read(ROOT / "CHANGELOG.md").split("## [1.3.0]", 1)[1].split("\n## [", 1)[0]
    return unreleased.split(f"### {kind}", 1)[1].split("\n### ", 1)[0]


def _bullet(section: str, start: str) -> str:
    """The `- <start>…` bullet of a list, flattened, up to the next bullet."""
    m = re.search(rf"^- {re.escape(start)}(.*?)(?=^- |\Z)", section, flags=re.MULTILINE | re.DOTALL)
    assert m is not None, start
    return _flat(m.group(0))


OLD_LOGS = (
    "App logs written by earlier versions (`logs\\app.log` and its numbered copies) may hold Wi-Fi keys, APN "
    "passwords and SIM PINs typed in the AT console; delete them."
)


OLD_LOGS_DELETED = (
    "Version 1.4.0 and later delete them once, on their first start. If one cannot be deleted, for example "
    "while another program has it open, the app log names it and each start deletes the app logs again. "
    "With 1.3.0, delete them yourself."
)


def test_old_app_logs_are_named_as_holding_secrets() -> None:
    """P14 (security M2): 1.3.0's app-log fix tells users to delete their old logs. Since #112 the app deletes
    them once, on its first start, and the CHANGELOG and SECURITY.md say so."""
    assert OLD_LOGS in _bullet(_unreleased("Fixed"), "App log:")
    security = (
        _read(ROOT / "SECURITY.md").split("## Secrets on screen and in the log", 1)[1].split("\n## ", 1)[0]
    )
    own_log = _bullet(security, "**The app's own log**")
    assert OLD_LOGS.removesuffix("; delete them.") in own_log
    assert OLD_LOGS_DELETED in own_log
    unreleased = _read(ROOT / "CHANGELOG.md").split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    security_notes = unreleased.split("### Security", 1)[1].split("\n### ", 1)[0]
    assert "on its first start, the app deletes the app logs written by earlier versions" in _bullet(
        security_notes, "App log:"
    )
    where = _section("Troubleshooting", "Where are the logs?")
    assert "deletes the app logs written by earlier versions, once" in where
    assert "each start deletes the app logs again until it can delete them all" in where


def test_never_on_the_last_try_is_enter_pins_alone() -> None:
    """P17: Enter PIN never spends the last try (E3, P15); the AT console sends what is typed after its
    question. No page may say the app as a whole never does."""
    sim = _section("LTE-modem", "SIM PIN")
    assert "**Enter PIN** never sends the PIN on the last try" in sim
    assert "nor when the modem does not say how many tries are left" in sim
    assert "the app does not send the PIN" not in sim
    assert "The AT console has no such check: it sends what you type" in sim
    console = _section("LTE-modem", "AT console")
    assert "does not check the SIM's tries left" in console and "**Enter PIN**" in console
    security = _read(ROOT / "SECURITY.md")
    enter_pin = _bullet(security, "**Enter PIN**")
    assert "Enter PIN never sends the PIN on the SIM's last try" in enter_pin
    assert "sends what you type" in _bullet(security, "**The AT console**")
    added = _bullet(_unreleased("Added"), "LTE modem › **SIM PIN**")
    assert "The app never sends the PIN on the last try" not in added
    assert "Enter PIN never sends it on the last try" in added


def test_uninstall_deletes_the_lte_setups() -> None:
    """Spec 4.4: saved good setups hold APN passwords and SIM PINs, so Yes deletes them as it does backups,
    and a folder that stays is named."""
    iss = _read(ROOT / "installer" / "OpenWrtGUI.iss")
    assert "lte-setups" in set(_ISS_DELETES.findall(iss))
    body = iss.split("procedure DeleteAppData", 1)[1].split("\nend;", 1)[0]
    assert "DirExists(Dir + '\\lte-setups')" in body


def test_uninstall_says_when_secrets_remain() -> None:
    """PR #74 review (2026-11-16): a locked or access-denied file can keep backups\\ or keys\\ after Yes, and
    DelTree's result was ignored. The uninstaller then names the folders still there instead of finishing
    silently, without failing the uninstall."""
    iss = _read(ROOT / "installer" / "OpenWrtGUI.iss")
    body = iss.split("procedure DeleteAppData", 1)[1].split("\nend;", 1)[0]
    for folder in ("backups", "keys"):
        assert f"DirExists(Dir + '\\{folder}')" in body, folder
    assert "mbError, MB_OK" in body and "by hand" in body
    files = _section("Files-and-data", "Moving or removing")
    assert "cannot be deleted" in files and "by hand" in files


def test_bench_router_names_only_in_pictures_and_examples() -> None:
    """v1.0d D3: AP1/AP2 appear in screenshot alt text and `code` examples, not in sentences."""
    found = []
    for page, text in _user_pages().items():
        prose = _CODE_SPAN.sub("", _IMAGE.sub("", text))
        found += [(page, m.group(0)) for m in re.finditer(r"\bAP\d\b", prose)]
    assert found == []
