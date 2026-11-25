"""The SMS card's endpoints (v1.3b E5, E6, E7) in the simulator: list, read, delete and send, each write
behind a preview and its digest, the text of a message shown nowhere in the audit."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.lte import commands as c
from openwrtgui.lte.sms import GSM_RULE
from openwrtgui.simmodem import SimModem
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import ReplayTransport

BASE = "/api/routers/ap1/lte/sms"
DEV = "/dev/cdc-wdm0"
CARRIER = "This sends an SMS from the router's SIM to +15550104; the carrier may charge for it"
CHANGED = "The message list changed; preview again"
BUSY = "An LTE action is already running on AP1 · bench"


async def _modem(ctx: AppContext) -> SimModem:
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


def _audited(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


def _delete_lines(*ids: int) -> list[str]:
    return [c.delete_message(DEV, "sim", i) for i in ids]


async def _preview_delete(client: httpx.AsyncClient, *ids: int) -> httpx.Response:
    return await client.post(f"{BASE}/delete/preview", json={"storage": "sim", "ids": list(ids)})


async def _preview_send(client: httpx.AsyncClient, text: str = "Hello there") -> httpx.Response:
    return await client.post(f"{BASE}/send/preview", json={"target": "+15550104", "text": text})


# ---------------------------------------------------------------- the list and one message
async def test_the_sim_list_with_its_use(authed: httpx.AsyncClient) -> None:
    answer = await authed.get(BASE, params={"storage": "sim"})
    assert (answer.status_code, answer.json()) == (
        200,
        {"storage": "sim", "ids": [0, 1, 2], "used": 3, "capacity": 20, "full": False},
    )


async def test_the_list_defaults_to_the_sim(authed: httpx.AsyncClient) -> None:
    assert (await authed.get(BASE)).json()["storage"] == "sim"


async def test_the_phone_memory_list_is_empty_with_its_own_capacity(authed: httpx.AsyncClient) -> None:
    body = (await authed.get(BASE, params={"storage": "me"})).json()
    assert body == {"storage": "me", "ids": [], "used": 0, "capacity": 23, "full": False}


async def test_a_full_sim_says_full(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.messages["sim"] = {i: {"sender": "+15550101", "text": f"Test message {i}"} for i in range(20)}
    body = (await authed.get(BASE, params={"storage": "sim"})).json()
    assert (body["used"], body["capacity"], body["full"]) == (20, 20, True)


async def test_no_at_port_leaves_the_use_unknown(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    modem = await _modem(ctx)
    real = modem.answer

    def no_cpms(command: str) -> CommandResult | None:
        if "AT+CPMS?" in command:
            return CommandResult(command, "", "", 1)
        return real(command)

    modem.answer = no_cpms  # type: ignore[method-assign]
    body = (await authed.get(BASE, params={"storage": "sim"})).json()
    assert (body["ids"], body["used"], body["capacity"], body["full"]) == ([0, 1, 2], None, None, False)


async def test_a_dead_cached_at_port_is_forgotten_so_the_next_read_probes_again(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    modem = await _modem(ctx)
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport)
    await authed.get(BASE, params={"storage": "sim"})  # finds and keeps the AT port
    real = modem.answer

    def dead(command: str) -> CommandResult | None:
        if "AT+CPMS?" in command:
            return CommandResult(command, "", "", 1)  # the kept port no longer answers
        return real(command)

    modem.answer = dead  # type: ignore[method-assign]
    body = (await authed.get(BASE, params={"storage": "sim"})).json()
    assert (body["used"], body["capacity"]) == (None, None)
    modem.answer = real  # type: ignore[method-assign]
    probes = t.calls.count(c.TTY_LIST)
    assert (await authed.get(BASE, params={"storage": "sim"})).json()["used"] == 3
    assert t.calls.count(c.TTY_LIST) == probes + 1  # the dead port was dropped: found again


async def test_the_list_is_a_read_that_is_not_audited(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await authed.get(BASE, params={"storage": "sim"})
    assert ctx.audit.query() == []


async def test_a_message_is_read(authed: httpx.AsyncClient) -> None:
    answer = await authed.get(f"{BASE}/sim/1")
    assert answer.status_code == 200
    body = answer.json()
    assert (body["id"], body["storage"], body["sender"], body["text"]) == (
        1,
        "sim",
        "+15550102",
        "Test message 2",
    )


async def test_reading_a_message_audits_the_command_and_never_the_text(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    await authed.get(f"{BASE}/sim/1")
    assert _audited(ctx) == [c.get_message(DEV, "sim", 1)]
    assert "--get-message 1 --storage sim" in _audited(ctx)[0]
    assert not any("Test message 2" in e.command for e in ctx.audit.query())


async def test_a_live_guard_still_reads_a_message_but_refuses_delete_and_send(
    authed_guard_live: httpx.AsyncClient, ctx_guard_live: AppContext
) -> None:
    read = await authed_guard_live.get(f"{BASE}/sim/1")
    assert (read.status_code, read.json()["text"]) == (200, "Test message 2")
    assert (await authed_guard_live.get(BASE)).status_code == 200
    delete_digest = (await _preview_delete(authed_guard_live, 1)).json()["digest"]
    send_digest = (await _preview_send(authed_guard_live)).json()["digest"]
    modem = await _modem(ctx_guard_live)
    delete = await authed_guard_live.post(
        f"{BASE}/delete/apply", json={"storage": "sim", "ids": [1], "digest": delete_digest}
    )
    send = await authed_guard_live.post(
        f"{BASE}/send/apply", json={"target": "+15550104", "text": "Hello there", "digest": send_digest}
    )
    assert (delete.status_code, send.status_code) == (423, 423)
    assert sorted(modem.messages["sim"]) == [0, 1, 2] and modem.sent == []
    assert _audited(ctx_guard_live) == [c.get_message(DEV, "sim", 1)]


async def test_a_message_that_is_not_in_the_list_is_a_404(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    answer = await authed.get(f"{BASE}/sim/9")
    assert (answer.status_code, answer.json()) == (404, {"detail": "No message 9 in sim"})
    assert ctx.audit.query() == []


async def test_a_bad_storage_or_id_is_a_422(authed: httpx.AsyncClient) -> None:
    assert (await authed.get(BASE, params={"storage": "x"})).status_code == 422
    assert (await authed.get(f"{BASE}/x/1")).status_code == 422
    assert (await authed.get(f"{BASE}/sim/-1")).status_code == 422
    assert (await authed.post(f"{BASE}/delete/preview", json={"storage": "x", "ids": [1]})).status_code == 422
    assert (
        await authed.post(f"{BASE}/delete/preview", json={"storage": "sim", "ids": [-1]})
    ).status_code == 422
    assert (
        await authed.post(f"{BASE}/delete/preview", json={"storage": "sim", "ids": []})
    ).status_code == 422


async def test_an_unknown_router_is_a_404(authed: httpx.AsyncClient) -> None:
    assert (await authed.get("/api/routers/nope/lte/sms")).status_code == 404
    assert (await authed.get("/api/routers/nope/lte/sms/sim/0")).status_code == 404


# ---------------------------------------------------------------- Delete
async def test_the_delete_preview_is_the_exact_commands(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    answer = await _preview_delete(authed, 1, 2)
    assert answer.status_code == 200
    body = answer.json()
    assert body["lines"] == _delete_lines(1, 2)
    assert body["digest"]
    assert ctx.audit.query() == []
    assert sorted((await _modem(ctx)).messages["sim"]) == [0, 1, 2]


async def test_delete_of_an_id_not_in_the_list_is_a_404_at_the_preview(authed: httpx.AsyncClient) -> None:
    answer = await _preview_delete(authed, 1, 9)
    assert (answer.status_code, answer.json()) == (404, {"detail": "No message 9 in sim"})


async def test_apply_deletes_the_previewed_messages(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    digest = (await _preview_delete(authed, 1, 2)).json()["digest"]
    answer = await authed.post(
        f"{BASE}/delete/apply", json={"storage": "sim", "ids": [1, 2], "digest": digest}
    )
    assert (answer.status_code, answer.json()) == (
        200,
        {"ok": True, "lines": _delete_lines(1, 2), "error": None},
    )
    assert sorted((await _modem(ctx)).messages["sim"]) == [0]
    assert _audited(ctx) == _delete_lines(1, 2)


async def test_a_message_deleted_after_the_preview_is_a_409_and_nothing_is_deleted(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    """Review Focus 2: the list changed between the preview and Apply."""
    digest = (await _preview_delete(authed, 1, 2)).json()["digest"]
    modem = await _modem(ctx)
    del modem.messages["sim"][2]
    answer = await authed.post(
        f"{BASE}/delete/apply", json={"storage": "sim", "ids": [1, 2], "digest": digest}
    )
    assert (answer.status_code, answer.json()) == (409, {"detail": CHANGED})
    assert sorted(modem.messages["sim"]) == [0, 1]
    assert ctx.audit.query() == []


async def test_a_digest_of_another_preview_is_a_409(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    digest = (await _preview_delete(authed, 1)).json()["digest"]
    answer = await authed.post(
        f"{BASE}/delete/apply", json={"storage": "sim", "ids": [1, 2], "digest": digest}
    )
    assert answer.status_code == 409
    assert sorted((await _modem(ctx)).messages["sim"]) == [0, 1, 2]


async def test_delete_stops_at_the_first_failure(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    digest = (await _preview_delete(authed, 0, 1, 2)).json()["digest"]
    modem = await _modem(ctx)
    real = modem.answer

    def refuses_one(command: str) -> CommandResult | None:
        if "--delete-message 1 " in command:
            return CommandResult(command, "", "Request failed\n", 1)
        return real(command)

    modem.answer = refuses_one  # type: ignore[method-assign]
    answer = await authed.post(
        f"{BASE}/delete/apply", json={"storage": "sim", "ids": [0, 1, 2], "digest": digest}
    )
    body = answer.json()
    assert (answer.status_code, body["ok"], body["lines"], body["error"]) == (
        200,
        False,
        _delete_lines(0),
        "Request failed",
    )
    assert sorted(modem.messages["sim"]) == [1, 2]
    assert _audited(ctx) == _delete_lines(0, 1)


async def test_delete_while_another_lte_write_runs_is_a_409(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    digest = (await _preview_delete(authed, 1)).json()["digest"]
    async with ctx.lte.write_slot(ctx.routers.get("ap1")):  # type: ignore[arg-type]
        answer = await authed.post(
            f"{BASE}/delete/apply", json={"storage": "sim", "ids": [1], "digest": digest}
        )
    assert (answer.status_code, answer.json()) == (409, {"detail": BUSY})
    assert sorted((await _modem(ctx)).messages["sim"]) == [0, 1, 2]


# ---------------------------------------------------------------- Send
async def test_the_send_preview_is_the_command_with_the_carrier_warning(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    answer = await _preview_send(authed)
    assert answer.status_code == 200
    body = answer.json()
    assert body["lines"] == [c.send_message(DEV, "+15550104", "Hello there")]
    assert body["warnings"] == [CARRIER]
    assert ctx.audit.query() == [] and (await _modem(ctx)).sent == []


async def test_apply_sends_and_the_audit_hides_the_text_but_not_the_number(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    digest = (await _preview_send(authed)).json()["digest"]
    answer = await authed.post(
        f"{BASE}/send/apply", json={"target": "+15550104", "text": "Hello there", "digest": digest}
    )
    assert answer.status_code == 200 and answer.json()["ok"] is True
    assert (await _modem(ctx)).sent == [("+15550104", "Hello there")]
    (audited,) = _audited(ctx)
    assert "<hidden>" in audited and "Hello there" not in audited
    assert "--send-message-target +15550104" in audited


AUDITED_SEND = "uqmi -s -d /dev/cdc-wdm0 -t 10000 --send-message '<hidden>' --send-message-target +15550104"


@pytest.mark.parametrize("text", ["It's ok", "a", "5", "0101", "line one\nline two", "Hello there"])
async def test_the_audit_hides_any_text_whole_and_keeps_the_number(
    authed: httpx.AsyncClient, ctx: AppContext, text: str
) -> None:
    """Final review I1 / security M1, L3: by position, so a `'` cannot leave the text in clear and a short
    text cannot shred the line or hide digits of the number (E6)."""
    body = {"target": "+15550101", "text": text}
    digest = (await authed.post(f"{BASE}/send/preview", json=body)).json()["digest"]
    answer = await authed.post(f"{BASE}/send/apply", json={**body, "digest": digest})
    assert answer.status_code == 200 and answer.json()["ok"] is True
    assert (await _modem(ctx)).sent == [("+15550101", text)]
    assert _audited(ctx) == [AUDITED_SEND.replace("+15550104", "+15550101")]


async def test_a_lost_connection_still_audits_the_text_hidden(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    """The TransportError path of run_audited masks the same way."""
    digest = (await _preview_send(authed, "It's ok")).json()["digest"]
    modem = await _modem(ctx)
    real = modem.answer

    def lost(command: str) -> CommandResult | None:
        if "--send-message " in command:
            raise TransportError("connection lost")
        return real(command)

    modem.answer = lost  # type: ignore[method-assign]
    answer = await authed.post(
        f"{BASE}/send/apply", json={"target": "+15550104", "text": "It's ok", "digest": digest}
    )
    assert answer.status_code == 502
    assert _audited(ctx) == [AUDITED_SEND]


async def test_a_changed_text_is_a_409_and_sends_nothing(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    digest = (await _preview_send(authed)).json()["digest"]
    answer = await authed.post(
        f"{BASE}/send/apply", json={"target": "+15550104", "text": "Another text", "digest": digest}
    )
    assert answer.status_code == 409
    assert (await _modem(ctx)).sent == [] and ctx.audit.query() == []


async def test_a_text_outside_the_gsm_set_is_a_422_with_the_rule(authed: httpx.AsyncClient) -> None:
    """Review Focus 5."""
    answer = await _preview_send(authed, "é")
    assert (answer.status_code, answer.json()) == (422, {"detail": GSM_RULE})


async def test_a_bad_number_or_a_long_text_is_a_422(authed: httpx.AsyncClient) -> None:
    bad = await authed.post(f"{BASE}/send/preview", json={"target": "12", "text": "x"})
    assert (bad.status_code, bad.json()) == (422, {"detail": c.TARGET_MESSAGE})
    long = await authed.post(f"{BASE}/send/preview", json={"target": "+15550104", "text": "x" * 501})
    assert long.status_code == 422


async def test_send_while_an_lte_action_holds_the_slot_is_a_409(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    digest = (await _preview_send(authed)).json()["digest"]
    async with ctx.lte.write_slot(ctx.routers.get("ap1")):  # type: ignore[arg-type]
        answer = await authed.post(
            f"{BASE}/send/apply", json={"target": "+15550104", "text": "Hello there", "digest": digest}
        )
    assert (answer.status_code, answer.json()) == (409, {"detail": BUSY})
    assert (await _modem(ctx)).sent == []


@pytest.mark.parametrize("path", ["delete/preview", "send/preview"])
async def test_an_unknown_router_is_a_404_for_the_writes_too(authed: httpx.AsyncClient, path: str) -> None:
    body = (
        {"storage": "sim", "ids": [1]} if path.startswith("delete") else {"target": "+15550104", "text": "x"}
    )
    assert (await authed.post(f"/api/routers/nope/lte/sms/{path}", json=body)).status_code == 404
