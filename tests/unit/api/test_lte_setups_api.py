"""Save good setup and the setup list on the simulator (spec 4.4)."""

from __future__ import annotations

import httpx

from openwrtgui.context import AppContext
from openwrtgui.lte.settings import LteSettings
from openwrtgui.net.apply import NOTHING
from openwrtgui.transport.fake import ReplayTransport

NOT_WORKING = "LTE does not work on AP2 · office right now; save a good setup while it works"


async def _modem(ctx: AppContext):  # type: ignore[no-untyped-def]
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


async def _with_secrets(ctx: AppContext) -> None:
    """The router's lte section gets an APN password and a SIM PIN (test values only)."""
    settings = LteSettings(apn="test-apn", password="secret-pw", pincode="1234")
    plan = await ctx.lte.plan_settings("ap2", settings)
    result = await ctx.lte.apply_settings("ap2", settings, plan.digest)
    assert result.applied, result.error


async def test_save_refuses_when_lte_does_not_work(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    (await _modem(ctx)).wedged = True  # the session is up without a packet-data handle
    refused = await authed.post("/api/routers/ap2/lte/setup")
    assert (refused.status_code, refused.json()["detail"]) == (422, NOT_WORKING)
    assert ctx.lte_setups.get("ap2") is None


async def test_save_stores_the_editable_options_and_the_secrets(
    ctx: AppContext, authed: httpx.AsyncClient
) -> None:
    await _with_secrets(ctx)
    saved = await authed.post("/api/routers/ap2/lte/setup")
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["router_id"], body["router_name"], body["apn"], body["readable"]) == (
        "ap2",
        "AP2 · office",
        "test-apn",
        True,
    )
    assert "secret-pw" not in saved.text and "1234" not in saved.text and "options" not in body
    setup = ctx.lte_setups.get("ap2")
    assert setup is not None
    assert {k: setup.options.get(k) for k in ("apn", "password", "pincode", "mtu")} == {
        "apn": "test-apn",
        "password": "secret-pw",
        "pincode": "1234",
        "mtu": "1420",
    }
    assert "autoconnect" not in setup.options  # control-locked: the LTE screen keeps it
    assert "device" not in setup.options  # never copied (spec 4.4)
    assert setup.modem.model == "BM806C"


async def test_the_audit_line_hides_the_secrets(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    await _with_secrets(ctx)
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    commands = [e.command for e in ctx.audit.query()]
    assert "LTE good setup saved" in commands
    assert not any("secret-pw" in c or "1234" in c for c in commands)


async def test_the_list_names_every_saved_setup(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    assert (await authed.get("/api/lte-setups")).json() == []
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    (row,) = (await authed.get("/api/lte-setups")).json()
    assert (row["router_id"], row["apn"], row["pdptype"], row["readable"]) == (
        "ap2",
        "uinternet",
        "ipv4",
        True,
    )
    assert set(row) == {"router_id", "router_name", "saved_at", "apn", "pdptype", "readable"}


async def test_reconfigure_puts_the_saved_setup_back(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    await _with_secrets(ctx)
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    drift = LteSettings(apn="other", password="other-pw")
    plan = await ctx.lte.plan_settings("ap2", drift)
    assert (await ctx.lte.apply_settings("ap2", drift, plan.digest)).applied
    preview = await authed.post("/api/routers/ap2/lte/setup/preview", json={"source": "ap2"})
    assert preview.status_code == 200, preview.text
    lines = preview.json()["lines"]
    assert any("network.lte.apn='test-apn'" in line for line in lines)
    assert any("network.lte.password='<hidden>'" in line for line in lines)
    assert not any("secret-pw" in line for line in lines)
    applied = await authed.post(
        "/api/routers/ap2/lte/setup/apply", json={"source": "ap2", "digest": preview.json()["digest"]}
    )
    assert (applied.status_code, applied.json()["applied"]) == (200, True)
    _rows, values = await ctx.net.interface_values("ap2", "lte")
    assert (values["apn"], values["password"]) == ("test-apn", "secret-pw")


async def test_a_restore_that_matches_changes_nothing(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    """Every settings preview answers an empty change this way (net_plan's NOTHING, 422)."""
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    preview = await authed.post("/api/routers/ap2/lte/setup/preview", json={"source": "ap2"})
    assert (preview.status_code, preview.json()["detail"]) == (422, NOTHING)
    assert not any(e.command.startswith("uci") for e in ctx.audit.query())


async def _drift(ctx: AppContext) -> None:
    drift = LteSettings(apn="other")
    plan = await ctx.lte.plan_settings("ap2", drift)
    assert (await ctx.lte.apply_settings("ap2", drift, plan.digest)).applied


async def test_a_stale_digest_is_refused(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    await _drift(ctx)
    refused = await authed.post(
        "/api/routers/ap2/lte/setup/apply", json={"source": "ap2", "digest": "0000000000000000"}
    )
    assert refused.status_code == 409


async def test_a_missing_or_unreadable_setup(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    missing = await authed.post("/api/routers/ap2/lte/setup/preview", json={"source": "ap1"})
    assert (missing.status_code, missing.json()["detail"]) == (404, "No good setup saved for ap1")
    (ctx.data.lte_setups_dir / "ap1.json").write_text("{", encoding="utf-8")
    broken = await authed.post("/api/routers/ap2/lte/setup/preview", json={"source": "ap1"})
    assert (broken.status_code, broken.json()["detail"]) == (422, "ap1.json cannot be read")


async def test_an_option_without_a_row_is_named_in_the_preview(
    ctx: AppContext, authed: httpx.AsyncClient
) -> None:
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    setup = ctx.lte_setups.get("ap2")
    assert setup is not None
    ctx.lte_setups.save(setup.model_copy(update={"options": {**setup.options, "bogus": "1"}}))
    warning = "Not restored (no such option on AP2 · office): bogus"
    nothing = await authed.post("/api/routers/ap2/lte/setup/preview", json={"source": "ap2"})
    assert (nothing.status_code, nothing.json()["detail"]) == (422, f"{NOTHING} {warning}.")
    await _drift(ctx)
    preview = await authed.post("/api/routers/ap2/lte/setup/preview", json={"source": "ap2"})
    assert warning in preview.json()["warnings"]
    assert not any("bogus" in line for line in preview.json()["lines"])


async def test_removing_a_router_deletes_its_setup(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    assert (await authed.post("/api/routers/ap2/lte/setup")).status_code == 200
    path = ctx.data.lte_setups_dir / "ap2.json"
    assert path.is_file()
    assert (await authed.delete("/api/routers/ap2")).status_code == 200
    assert not path.exists()
