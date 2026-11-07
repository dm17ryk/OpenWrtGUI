"""Custom rule files (/etc/nftables.d): checked with fw4 print | nft -c, applied with a timer rollback."""

from __future__ import annotations

import pytest
from fwenv import FwEnv

from openwrtgui.fw.custom import CustomRequest

IMAGE = "/etc/nftables.d/10-custom-filter-chains.nft"
NEW = "/etc/nftables.d/20-owg.nft"
CHAIN = "chain owg_c {\n\ttype filter hook input priority 5; policy accept;\n}"
CHECK = "fw4 print > /tmp/owg/rb-<rollback>.check && nft -c -f /tmp/owg/rb-<rollback>.check"


async def test_image_file_marked(env: FwEnv) -> None:
    (f,) = (await env.fw.state("ap2")).custom
    assert (f.path, f.name, f.from_image, f.comments_only) == (IMAGE, "10-custom-filter-chains", True, True)
    assert f.lines == f.content.count("\n")


async def test_custom_file_plan(env: FwEnv) -> None:
    plan = await env.fw.plan_custom("ap2", CustomRequest("20-owg", CHAIN))
    lines = plan.lines
    assert lines[0] == "set -e"
    assert lines[1].startswith("mkdir -p /tmp/owg && start-stop-daemon -S")
    assert f"rm -f {NEW}; fw4 reload" in lines[1]
    start = lines.index(f"cat > {NEW} <<'OWG'")
    assert lines[start + 1 : start + 5] == (
        "chain owg_c {",
        "\ttype filter hook input priority 5; policy accept;",
        "}",
        "OWG",
    )
    assert lines[start + 5 :] == (
        CHECK,
        "fw4 reload",
        "start-stop-daemon -K -q -p /tmp/owg/rb-<rollback>.pid; rm -f /tmp/owg/rb-<rollback>.pid; "
        "rm -f /tmp/owg/rb-<rollback>*",
    )


async def test_edit_backs_up_the_old_file(env: FwEnv) -> None:
    plan = await env.fw.plan_custom("ap2", CustomRequest("10-custom-filter-chains", "# nothing here\n"))
    assert plan.lines[1] == f"cp {IMAGE} /tmp/owg/rb-<rollback>.bak"
    assert f"cp /tmp/owg/rb-<rollback>.bak {IMAGE}; fw4 reload" in plan.lines[2]


async def test_custom_apply_verified_in_sim(env: FwEnv) -> None:
    req = CustomRequest("20-owg", CHAIN)
    plan = await env.fw.plan_custom("ap2", req)
    result = await env.fw.apply_custom("ap2", req, plan.digest)
    assert result.applied and result.verified, result
    assert {"file /etc/nftables.d/20-owg.nft", "fw4"} <= {c.name for c in result.checks}
    assert [f.name for f in (await env.fw.state("ap2")).custom] == ["10-custom-filter-chains", "20-owg"]
    gone = CustomRequest("20-owg", None)
    plan = await env.fw.plan_custom("ap2", gone)
    assert f"rm -f {NEW}" in plan.lines
    assert (await env.fw.apply_custom("ap2", gone, plan.digest)).verified
    assert [f.name for f in (await env.fw.state("ap2")).custom] == ["10-custom-filter-chains"]


async def test_refused_rules_restore_the_old_file_at_once(env: FwEnv) -> None:
    before = (await env.fw.state("ap2")).custom[0].content
    req = CustomRequest("10-custom-filter-chains", "chain broken {\n")
    plan = await env.fw.plan_custom("ap2", req)
    result = await env.fw.apply_custom("ap2", req, plan.digest)
    assert not result.applied
    assert result.error is not None and result.error.startswith(
        "The router refused the change: Error: syntax error"
    )
    assert (await env.fw.state("ap2")).custom[0].content == before


async def test_name_rules(env: FwEnv) -> None:
    with pytest.raises(ValueError, match="^A rules file name is 1 to 60 letters, digits, - or _$"):
        await env.fw.plan_custom("ap2", CustomRequest("../x", "# x"))
    with pytest.raises(ValueError, match="^A rules file is at most 64 KiB$"):
        await env.fw.plan_custom("ap2", CustomRequest("big", "#" * (64 * 1024 + 1)))
    with pytest.raises(ValueError, match="^The text may not contain a line that reads OWG$"):
        await env.fw.plan_custom("ap2", CustomRequest("x", "# a\nOWG\n"))
    with pytest.raises(ValueError, match="^There is no rules file x$"):
        await env.fw.plan_custom("ap2", CustomRequest("x", None))
