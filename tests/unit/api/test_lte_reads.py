"""GET /lte (v1.0c D2): the modem's identity and mode order once per connection, the operator always."""

from __future__ import annotations

import httpx
from readcount import at_exchanges, count_read

from openwrtgui.context import AppContext

LTE = "/api/routers/ap1/lte"


async def test_a_second_read_asks_the_modem_only_its_operator(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    await authed.get(LTE)
    sent = await count_read(authed, ctx, "ap1", "GET", LTE)
    assert [x for x in sent if "microcom" in x] == [x for x in sent if "AT+COPS?" in x]
    assert at_exchanges(sent) == 1


async def test_an_at_write_reads_the_identity_again(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await authed.get(LTE)
    await authed.post(f"{LTE}/at", json={"command": "AT+BMMODODR=2", "confirmed": True})
    sent = await count_read(authed, ctx, "ap1", "GET", LTE)
    assert any("AT+CGMI" in x for x in sent) and any("AT+BMMODODR?" in x for x in sent)


async def test_a_new_connection_reads_the_identity_again(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    await authed.get(LTE)
    await ctx.pool.drop("ap1")
    sent = await count_read(authed, ctx, "ap1", "GET", LTE)
    assert any("AT+CGMI" in x for x in sent)


async def test_the_identity_shows_on_the_second_read(authed: httpx.AsyncClient) -> None:
    first = (await authed.get(LTE)).json()["modem"]
    second = (await authed.get(LTE)).json()["modem"]
    assert second == first and second["model"]
