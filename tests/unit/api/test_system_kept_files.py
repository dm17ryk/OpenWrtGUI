"""Files kept in a backup (/etc/sysupgrade.conf, plan D10) and importing a backup file (D11), in the
simulator."""

from __future__ import annotations

import io
import tarfile

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.system.backup import backup_dir


async def test_kept_files_edit_read_back(ctx: AppContext) -> None:
    kept = await ctx.system.kept_files("ap2")
    assert kept.text.startswith("## This file contains files and directories")
    assert "/etc/config/dropbear" in kept.listed
    wanted = kept.text + "/etc/owg-test.conf\n"
    plan = await ctx.system.plan_kept_files("ap2", wanted)
    assert plan.lines[0] == "cat > /etc/sysupgrade.conf <<'OWG'" and "/etc/owg-test.conf" in plan.lines
    result = await ctx.system.apply_kept_files("ap2", wanted, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert (await ctx.system.kept_files("ap2")).text == wanted


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("etc/relative\n", "line 1"),
        ("# fine\n/etc/a b\n", "line 2"),
        ("OWG\n", "line 1"),
        ("/" + "x" * 200 + "\n" + ("/etc/y\n" * 1300), "8 KiB"),
    ],
)
async def test_kept_files_refusals(ctx: AppContext, text: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        await ctx.system.plan_kept_files("ap2", text)


async def test_owg_line_removal_warns(ctx: AppContext) -> None:
    kept = (await ctx.system.kept_files("ap2")).text
    with_owg = kept + "/etc/owg/\n"
    await ctx.system.apply_kept_files(
        "ap2", with_owg, (await ctx.system.plan_kept_files("ap2", with_owg)).digest
    )
    plan = await ctx.system.plan_kept_files("ap2", kept)
    assert any("adds /etc/owg/ back" in w for w in plan.warnings)


def _archive(extra: tarfile.TarInfo | None = None) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        data = b"config system\n\toption hostname 'old'\n"
        info = tarfile.TarInfo("etc/config/system")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        if extra is not None:
            tar.addfile(extra)
    return raw.getvalue()


async def test_import_listed_and_refused(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    data = _archive()
    saved = await authed.post(
        "/api/routers/ap2/system/backups/import", content=data, headers={"X-File-Name": "ap2-old.tar.gz"}
    )
    assert saved.status_code == 200, saved.text
    name = saved.json()["name"]
    assert name.startswith("ap2-") and name.endswith("-imported.tar.gz") and saved.json()["imported"] is True
    listed = (await authed.get("/api/routers/ap2/system/backups")).json()
    assert [(b["name"], b["imported"]) for b in listed] == [(name, True)]
    assert (await authed.get(f"/api/routers/ap2/system/backups/{name}")).content == data
    audit = [e.command for e in ctx.audit.query()]
    assert any(c.startswith("import ap2-old.tar.gz (") and name in c for c in audit)
    link = tarfile.TarInfo("etc/config/x")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/shadow"
    refused = await authed.post(
        "/api/routers/ap2/system/backups/import", content=_archive(link), headers={"X-File-Name": "x.tar.gz"}
    )
    assert refused.status_code == 422 and "a link or a device" in refused.json()["detail"]
    folder = backup_dir(ctx.data.root, "ap2")
    assert sorted(p.name for p in folder.iterdir()) == [name]  # nothing left of the refused one
    bad_name = await authed.post(
        "/api/routers/ap2/system/backups/import", content=data, headers={"X-File-Name": "../x"}
    )
    assert bad_name.status_code == 422
