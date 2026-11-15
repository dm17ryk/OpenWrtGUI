"""ap5 (v1.0a3 D5): a simulated DSA router whose reachability follows its bridge VLANs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openwrtgui.simnet import SimNetwork
from openwrtgui.simulator import SIM_SEED_ENV, seed_routers
from openwrtgui.store.routers import RouterStore

SIM = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
P = "uci -P /var/run/rpcd/uci-s1"
APPLY = 'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"s1"}\''


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _ap5(clock: Clock | None = None) -> SimNetwork:
    return SimNetwork(
        (SIM / "net" / "ap5.uci").read_text("utf-8"),
        dsa_ports=("lan1", "lan2", "lan3", "lan4", "wan"),
        dsa_pc_port="lan3",
        clock=clock or Clock(),
    )


def _status(sim: SimNetwork) -> dict[str, Any]:
    result = sim.answer("ubus call network.device status")
    assert result is not None and result.ok
    value: dict[str, Any] = json.loads(result.stdout)
    return value


def _apply(sim: SimNetwork, *lines: str) -> None:
    staged = sim.answer("\n".join(["set -e", "mkdir -p /var/run/rpcd/uci-s1", *lines]))
    assert staged is not None and staged.ok, staged
    done = sim.answer(APPLY)
    assert done is not None and done.ok, done


def test_device_status_as_netifd_reports_a_dsa_bridge() -> None:
    sim = _ap5()
    status = _status(sim)
    assert status["switch"]["type"] == "bridge"
    assert status["switch"]["bridge-members"] == ["lan1", "lan2", "lan3", "lan4"]
    assert status["switch"]["bridge-vlans"] == [  # netifd's format, pinned literally (D4)
        {"id": 1, "local": True, "local_pvid": False, "ports": ["lan1", "lan2", "lan3", "lan4"]},
        {"id": 10, "local": True, "local_pvid": False, "ports": ["lan1:t", "lan4:t"]},
    ]
    carriers = {k: status[k]["carrier"] for k in ("lan1", "lan3", "wan")}
    assert carriers == {"lan1": False, "lan3": True, "wan": False}
    assert status["switch.1"]["type"] == "VLAN" and status["switch.10"]["type"] == "VLAN"
    sim.dsa_links.add("lan1")
    assert _status(sim)["lan1"]["carrier"] is True
    sim.dsa_wifi.append("phy0-ap0")
    assert _status(sim)["switch"]["bridge-members"][-1] == "phy0-ap0"


def test_the_pc_reaches_lan_through_its_bridge_vlan() -> None:
    sim = _ap5()
    assert sim.reachable()
    _apply(sim, f"{P} -q delete network.cfg040f15.ports", f"{P} add_list network.cfg040f15.ports='lan1'")
    assert not sim.reachable()  # lan3 left VLAN 1


def test_a_tagged_pc_port_or_local_off_cuts_the_app_off_until_the_rollback() -> None:
    clock = Clock()
    sim = _ap5(clock)
    _apply(sim, f"{P} set network.cfg040f15.local='0'")
    assert not sim.reachable()
    clock.t += 61
    assert sim.reachable()  # rpcd restored the previous settings
    _apply(sim, f"{P} -q delete network.cfg040f15.ports", f"{P} add_list network.cfg040f15.ports='lan3:t'")
    assert not sim.reachable()


def test_another_clients_pending_rollback_refuses_an_apply() -> None:
    sim = _ap5()
    sim.pending_rollback(30)
    script = ["set -e", "mkdir -p /var/run/rpcd/uci-s1", f"{P} set network.cfg050f15.local='0'"]
    staged = sim.answer("\n".join(script))
    assert staged is not None and staged.ok
    refused = sim.answer(APPLY)
    assert refused is not None and not refused.ok and "Permission denied" in refused.stderr


def test_ap5_is_seeded_only_when_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SIM_SEED_ENV, raising=False)
    store = RouterStore(tmp_path / "a.json")
    seed_routers(SIM, store)
    assert store.get("ap5") is None
    monkeypatch.setenv(SIM_SEED_ENV, "ap4,ap5")
    named = RouterStore(tmp_path / "b.json")
    seed_routers(SIM, named)
    ap5 = named.get("ap5")
    assert ap5 is not None and (ap5.name, ap5.host) == ("AP5 · DSA image", "192.168.1.7")


def test_ap2_reports_no_bridge_vlans() -> None:
    sim = SimNetwork((SIM / "net" / "ap2.uci").read_text("utf-8"))
    assert "bridge-vlans" not in _status(sim)["br-lan"]
