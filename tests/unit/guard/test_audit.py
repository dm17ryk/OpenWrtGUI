import json
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from openwrtgui.guard.audit import AuditLog, mask


def test_secret_never_reaches_disk(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    log.record(
        router="ap2",
        screen="Add router",
        command="passwd root",
        exit_status=0,
        source="wizard",
        secrets=["s3cret!"],
    )
    log.record(
        router="ap2",
        screen="Wi-Fi",
        command="echo s3cret! | x",
        exit_status=0,
        source="user",
        secrets=["s3cret!"],
    )
    raw = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.jsonl"))
    assert "s3cret!" not in raw
    assert "<hidden>" in raw


def test_uci_key_masked() -> None:
    assert mask("uci set wireless.default_radio0.key='abc'", []) == (
        "uci set wireless.default_radio0.key='<hidden>'"
    )
    assert mask("uci set network.lte.password='p' && uci set network.lte.pincode='1234'", []) == (
        "uci set network.lte.password='<hidden>' && uci set network.lte.pincode='<hidden>'"
    )


def test_uci_secrets_masked_in_every_quoting() -> None:
    assert (
        mask("uci set wireless.default_radio0.key=s3cret", [])
        == "uci set wireless.default_radio0.key=<hidden>"
    )
    assert mask('uci set wireless.default_radio0.key="s3cret"', []) == (
        'uci set wireless.default_radio0.key="<hidden>"'
    )
    assert mask(
        "uci set wireless.wifinet1.sae_password=pw | x; uci set wireless.r.auth_secret='a b'", []
    ) == ("uci set wireless.wifinet1.sae_password=<hidden> | x; uci set wireless.r.auth_secret='<hidden>'")


def test_json_secrets_masked() -> None:
    command = 'ubus call uci set \'{"config":"wireless","values":{"key":"s3cret","ssid":"OpenWrt"}}\''
    assert mask(command, []) == (
        'ubus call uci set \'{"config":"wireless","values":{"key":"<hidden>","ssid":"OpenWrt"}}\''
    )


def test_shell_escaped_quote_inside_a_secret_is_masked_whole() -> None:
    # shell_quote("it's $x `y` z") writes the inner ' as '\'' ; the whole value must go.
    line = "uci set wireless.default_radio0.key='it'\\''s $x `y` z'"
    assert mask(line, ()) == "uci set wireless.default_radio0.key='<hidden>'"
    json_line = 'ubus call uci set \'{"values":{"key":"a\\"b c"}}\''
    assert mask(json_line, ()) == 'ubus call uci set \'{"values":{"key":"<hidden>"}}\''


def test_every_secret_option_the_router_has_is_masked() -> None:
    # options AP2's get_validate types as plain strings, WEP keys, and WireGuard keys (a typical LuCI page)
    for path in (
        "wireless.default_radio0.multi_ap_backhaul_key",
        "wireless.default_radio0.dae_secret",
        "wireless.default_radio0.auth_server_shared_secret",
        "wireless.default_radio0.acct_server_shared_secret",
        "wireless.default_radio0.private_key_passwd",
        "wireless.default_radio0.wps_pin",
        "wireless.default_radio0.ap_pin",
        "wireless.default_radio0.r0kh",
        "wireless.default_radio0.key1",
        "network.wg0.private_key",
        "network.wg_peer.preshared_key",
    ):
        assert mask(f"uci set {path}='s3cret'", []) == f"uci set {path}='<hidden>'", path


def test_empty_secret_ignored() -> None:
    assert mask("uname -a", ["", "x"]) == "uname -a"


def test_query_filters_and_order(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    for i, router in enumerate(["ap1", "ap2", "ap2"]):
        log.record(router=router, screen="Terminal", command=f"cmd{i}", exit_status=0, source="terminal")
    assert [e.command for e in log.query()] == ["cmd2", "cmd1", "cmd0"]
    assert [e.command for e in log.query(router="ap2")] == ["cmd2", "cmd1"]
    assert [e.command for e in log.query(text="cmd0")] == ["cmd0"]
    assert [e.command for e in log.query(limit=1)] == ["cmd2"]


def test_prune_respects_retention(tmp_path: Path) -> None:
    today = date(2026, 11, 3)
    for days in (100, 10):
        (tmp_path / f"{(today - timedelta(days=days)).isoformat()}.jsonl").write_text("", encoding="utf-8")
    log = AuditLog(tmp_path)
    assert log.prune(0, today) == 0
    assert log.prune(90, today) == 1
    assert [p.name for p in tmp_path.glob("*.jsonl")] == [f"{(today - timedelta(days=10)).isoformat()}.jsonl"]


def test_corrupt_line_is_skipped(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    entry = log.record(router=None, screen="Settings", command="ok", exit_status=None, source="app")
    day = tmp_path / f"{entry.ts.date().isoformat()}.jsonl"
    day.write_text(day.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    assert [e.command for e in log.query()] == ["ok"]


def _old_line(command: str) -> str:
    """An entry as 0.1.0 wrote it: `key1` and `wps_pin` were not on its secret list yet."""
    entry = {
        "ts": "2026-11-04T12:00:00+02:00",
        "router": "ap2",
        "screen": "Terminal",
        "command": command,
        "exit_status": 0,
        "verify": None,
        "source": "terminal",
    }
    return json.dumps(entry, ensure_ascii=False) + "\n"


OLD_COMMAND = "uci set wireless.wep.key1='s:wep-secret'; uci set wireless.ap.wps_pin='12345670'"


def test_entries_from_an_older_version_are_masked_when_shown(tmp_path: Path) -> None:
    (tmp_path / "2026-11-04.jsonl").write_text(_old_line(OLD_COMMAND), encoding="utf-8")
    [entry] = AuditLog(tmp_path).query()
    assert entry.command == "uci set wireless.wep.key1='<hidden>'; uci set wireless.ap.wps_pin='<hidden>'"


def test_entries_from_an_older_version_are_masked_in_the_export(tmp_path: Path) -> None:
    (tmp_path / "2026-11-04.jsonl").write_text(
        _old_line(OLD_COMMAND) + "{not json key1='s:wep-secret'\n", encoding="utf-8"
    )
    with zipfile.ZipFile(AuditLog(tmp_path).export_zip(tmp_path / "export.zip")) as z:
        text = z.read("2026-11-04.jsonl").decode("utf-8")
    assert "wep-secret" not in text and "12345670" not in text
    assert json.loads(text.splitlines()[0])["command"].endswith("wps_pin='<hidden>'")


def test_since_filter_and_export(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    log.record(router="ap2", screen="Terminal", command="uname", exit_status=0, source="terminal")
    assert log.query(since=datetime.now() + timedelta(minutes=1)) == []
    zpath = log.export_zip(tmp_path / "export.zip")
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith(".jsonl")
        assert json.loads(z.read(names[0]).decode("utf-8").splitlines()[0])["command"] == "uname"
