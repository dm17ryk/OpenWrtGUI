"""LTE settings through v0.3's interface plan for network.lte (rollback, D7, D8, D9) in the simulator."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.forms import OptionEdit
from openwrtgui.lte.settings import LteSettings

SESSION_SET = "uci -P /var/run/rpcd/uci-<session> set"
DHCP_LOCK = (
    "lte_4 must stay DHCP: the BM806C sends downlink only after a DHCP exchange binds this router's MAC"
)


async def test_apn_change_previews_and_applies_with_rollback(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    plan = await ctx.lte.plan_settings("ap2", LteSettings(apn="internet"))
    assert f"{SESSION_SET} network.lte.apn='internet'" in plan.lines
    assert plan.rollback
    preview = await authed.post("/api/routers/ap2/lte/settings/preview", json={"apn": "internet"})
    assert preview.status_code == 200 and preview.json()["digest"] == plan.digest
    applied = await authed.post(
        "/api/routers/ap2/lte/settings/apply", json={"apn": "internet", "digest": plan.digest}
    )
    assert (applied.status_code, applied.json()["applied"], applied.json()["verified"]) == (200, True, True)
    rows = {r.name: r for r in await ctx.lte.settings_options("ap2")}
    assert rows["apn"].value == "internet"


async def test_named_fields_become_options(ctx: AppContext) -> None:
    plan = await ctx.lte.plan_settings(
        "ap2", LteSettings(auth="chap", pdptype="ipv4v6", metric=10, defaultroute=False, mtu=1400, auto=False)
    )
    for line in (
        f"{SESSION_SET} network.lte.auth='chap'",
        f"{SESSION_SET} network.lte.pdptype='ipv4v6'",
        f"{SESSION_SET} network.lte.metric='10'",
        f"{SESSION_SET} network.lte.defaultroute='0'",
        f"{SESSION_SET} network.lte.mtu='1400'",
        f"{SESSION_SET} network.lte.auto='0'",
    ):
        assert line in plan.lines


async def test_password_is_hidden_in_the_preview_and_the_audit(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    plan = await ctx.lte.plan_settings("ap2", LteSettings(password="s3cr3t-pw", pincode="1234"))
    assert f"{SESSION_SET} network.lte.password='<hidden>'" in plan.lines
    assert f"{SESSION_SET} network.lte.pincode='<hidden>'" in plan.lines
    assert not any("s3cr3t-pw" in line or "1234" in line for line in plan.lines)
    applied = await authed.post(
        "/api/routers/ap2/lte/settings/apply",
        json={"password": "s3cr3t-pw", "pincode": "1234", "digest": plan.digest},
    )
    assert applied.status_code == 200
    assert not any("s3cr3t-pw" in e.command for e in ctx.audit.query())


async def test_an_empty_text_field_removes_the_option(ctx: AppContext) -> None:
    plan = await ctx.lte.plan_settings("ap2", LteSettings(apn=""))
    assert "uci -P /var/run/rpcd/uci-<session> -q delete network.lte.apn" in plan.lines


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (LteSettings(pincode="12"), "A SIM PIN is 4 to 8 digits"),
        (LteSettings(pincode="12345a"), "A SIM PIN is 4 to 8 digits"),
        (LteSettings(mtu=40), "MTU is 68 to 9000"),
        (LteSettings(edits=(OptionEdit("lte", "dhcp", "0"),)), DHCP_LOCK),
        (
            LteSettings(edits=(OptionEdit("lte_4", "hostname", "x"),)),
            "lte_4 is made by lte at run time; change lte instead.",
        ),
        (LteSettings(apn="a", edits=(OptionEdit("lte", "apn", "b"),)), "apn is given twice"),
    ],
)
async def test_settings_refusals(ctx: AppContext, settings: LteSettings, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        await ctx.lte.plan_settings("ap2", settings)


async def test_settings_options_lock_dhcp_and_autoconnect(authed: httpx.AsyncClient) -> None:
    got = await authed.get("/api/routers/ap2/lte/settings/options")
    assert got.status_code == 200
    rows = {r["name"]: r for r in got.json()}
    assert rows["dhcp"]["control"] == "LTE screen" and rows["autoconnect"]["control"] == "LTE screen"
    assert rows["password"]["editor"] == "secret" and rows["password"]["value"] is None
    bad = await authed.post("/api/routers/ap2/lte/settings/preview", json={"auth": "kerberos"})
    assert bad.status_code == 422
