"""The key rotation endpoints (v1.1b, spec 7.12, D8): preview, start with its digest, the job, retry, stop."""

from __future__ import annotations

import httpx

from openwrtgui.context import AppContext

BASE = "/api/app-key/rotation"


async def test_preview_start_job_round_trip(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    assert (await authed.get(BASE)).json() is None
    old = ctx.keys.current.fingerprint
    preview = await authed.post(f"{BASE}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert set(body) == {"lines", "warnings", "digest"} and body["lines"][0].startswith("Make a new app key")
    started = await authed.post(BASE, json={"digest": body["digest"]})
    assert started.status_code == 200 and started.json()["phase"] == "running"
    await ctx.key_rotation.finished()
    job = (await authed.get(BASE)).json()
    assert job["phase"] == "done" and job["old_fingerprint"] == old
    assert {r["state"] for r in job["routers"]} == {"moved"}
    key = (await authed.get("/api/app-key")).json()
    assert key["fingerprint"] == job["new_fingerprint"] != old and key["next_fingerprint"] is None


async def test_a_second_start_is_409_and_retry_waits_for_it(
    ctx: AppContext, authed: httpx.AsyncClient
) -> None:
    held = ctx.pool.write_lock("ap1")
    await held.acquire()  # another write on AP1: the rotation waits for it, so it is still running below
    try:
        digest = (await authed.post(f"{BASE}/preview")).json()["digest"]
        assert (await authed.post(BASE, json={"digest": digest})).status_code == 200
        again = await authed.post(BASE, json={"digest": digest})
        assert (again.status_code, again.json()["detail"]) == (409, "App key rotation already runs")
        retry = await authed.post(f"{BASE}/ap2/retry")
        assert retry.status_code == 409
        assert (await authed.post(f"{BASE}/stop")).status_code == 200
    finally:
        held.release()
    job = await ctx.key_rotation.finished()
    assert (
        job is not None and job.phase == "pending" and job.detail == "Stopped: the rest stay on the old key"
    )


async def test_a_stale_digest_is_409(authed: httpx.AsyncClient) -> None:
    refused = await authed.post(BASE, json={"digest": "0000000000000000"})
    assert refused.status_code == 409


async def test_a_harness_run_is_423(authed_guard_live: httpx.AsyncClient) -> None:
    preview = await authed_guard_live.post(f"{BASE}/preview")
    assert preview.status_code == 200  # reads only
    refused = await authed_guard_live.post(BASE, json={"digest": preview.json()["digest"]})
    assert refused.status_code == 423


async def test_retry_without_a_rotation_is_409(authed: httpx.AsyncClient) -> None:
    refused = await authed.post(f"{BASE}/ap2/retry")
    assert (refused.status_code, refused.json()["detail"]) == (409, "No key rotation is under way")
