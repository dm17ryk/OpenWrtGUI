"""Faults compiled to commands (spec 7.7): each its own nft chains on the target's device (netdev, else
bridge), tc netem in a band only the target reaches, swconfig port enable, hostapd calls; and the lines that
clear it, which a router-side timer runs when the fault is held for N s."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from openwrtgui.faults.commands import FAMILY_CHECKS
from openwrtgui.faults.model import ArmedFault, FaultCaps, FaultRequest, FaultTarget, NetemParams
from openwrtgui.fw.owners import APP_IFB, APP_ROOT, KERNEL_DEFAULTS
from openwrtgui.fw.tc import Qdisc
from openwrtgui.ports.compile import enable_commands
from openwrtgui.ports.state import PortsState
from openwrtgui.wifi.stations import del_client_command

__all__ = ["FAMILY_CHECKS", "CompiledFault", "compile_fault", "fault_id"]

TABLE = "benchfault"
SIP_PORTS = "{ 5060, 5061 }"
PRIOMAP = "1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1"  # prio's own map over three bands: nothing goes to band 4
NO_FAMILY = "This router's nftables cannot filter bridged traffic (needs kmod-nft-netdev or kmod-nft-bridge)"
HOLD_MIN, HOLD_MAX = 5, 86400
BAN_MIN, BAN_MAX = 10, 3600


@dataclass(frozen=True)
class CompiledFault:
    nft: tuple[str, ...]  # one nft transaction
    commands: tuple[str, ...]  # shell commands, in order
    chains: tuple[str, ...]
    clear: tuple[str, ...]
    summary: str
    device: str | None
    hold_s: int | None
    record: bool  # a fault that lasts gets a record in /tmp/owg (a deauth is over at once)


def fault_id(req: FaultRequest, armed: Sequence[str]) -> str:
    """The same request on the same router state gets the same id, so the preview and the apply digest
    alike; another fault armed in between gives another."""
    text = json.dumps(asdict(req), sort_keys=True) + "|" + ",".join(sorted(armed))
    return hashlib.sha256(text.encode()).hexdigest()[:6]


def _who(t: FaultTarget) -> str:
    return t.name or t.ip or t.mac or "the target"


def _station(t: FaultTarget) -> str:
    if t.via in (None, "wired"):
        raise ValueError(f"{_who(t)} is not on Wi-Fi (no station of an SSID on air)")
    assert t.via is not None
    return t.via


def _nft(req: FaultRequest, t: FaultTarget, caps: FaultCaps, rtp: Sequence[int], fid: str) -> CompiledFault:
    family = caps.family
    if family is None:
        raise ValueError(NO_FAMILY)
    loss = req.loss
    if not 1 <= loss <= 100:
        raise ValueError("Loss is 1 to 100 %")
    drop = f'{f"numgen random mod 100 < {loss} " if loss < 100 else ""}counter drop comment "owg:{fid}"'
    rules: list[tuple[str, str]] = []  # (to|from, match)
    if req.kind == "isolate":
        if not t.mac:
            raise ValueError(f"No MAC known for {t.ip}; enter one")
        rules = [("from", f"ether saddr {t.mac}"), ("to", f"ether daddr {t.mac}")]
        drop = f'counter drop comment "owg:{fid}"'
        summary = f"Isolate {_who(t)}"
    else:
        ip = t.ip
        ports = "{ " + ", ".join(str(p) for p in rtp) + " }"
        if req.flow in ("rtp_in", "rtp_out") and not rtp:
            raise ValueError(
                f"No RTP flow of {_who(t)} in conntrack: start the call first, or use all_in / all_out."
            )
        rules = {
            "rtp_in": [("to", f"ip daddr {ip} udp dport {ports}")],
            "rtp_out": [("from", f"ip saddr {ip} udp sport {ports}")],
            "sip_in": [("to", f"ip daddr {ip} meta l4proto {{ tcp, udp }} th sport {SIP_PORTS}")],
            "all_in": [("to", f"ip daddr {ip}")],
            "all_out": [("from", f"ip saddr {ip}")],
            "blackout": [("to", f"ip daddr {ip}"), ("from", f"ip saddr {ip}")],
        }.get(req.flow or "", [])
        if not rules:
            raise ValueError("Choose a flow: rtp_in, sip_in, rtp_out, all_in, all_out or blackout")
        summary = f"Block {req.flow} of {_who(t)}" + (f" · {loss} % loss" if loss < 100 else "")
    if family == "netdev" and not t.device:
        raise ValueError(f"Cannot tell which port of br-lan leads to {_who(t)}")
    chains: list[str] = []
    nft = [f"add table {family} {TABLE}"]
    for way in ("to", "from"):
        if not any(w == way for w, _ in rules):
            continue
        name = f"f{fid}_{way}"
        chains.append(name)
        if family == "netdev":
            hook = f'egress device "{t.device}"' if way == "to" else f'ingress device "{t.device}"'
            nft.append(f"add chain netdev {TABLE} {name} {{ type filter hook {hook} priority -500; }}")
        else:
            hook = "postrouting" if way == "to" else "prerouting"
            nft.append(f"add chain bridge {TABLE} {name} {{ type filter hook {hook} priority -300; }}")
    for way, match in rules:
        nft.append(f"add rule {family} {TABLE} f{fid}_{way} {match} {drop}")
    clear = tuple(
        line
        for c in chains
        for line in (f"nft flush chain {family} {TABLE} {c}", f"nft delete chain {family} {TABLE} {c}")
    )
    return CompiledFault(tuple(nft), (), tuple(chains), clear, summary, t.device, req.hold_s, True)


def _netem_params(n: NetemParams, caps: FaultCaps, router_name: str) -> str:
    if not 0 <= n.delay_ms <= 10000:
        raise ValueError("Delay is 0 to 10000 ms")
    if n.jitter_ms > n.delay_ms or n.jitter_ms < 0:
        raise ValueError("Jitter is at most the delay")
    if any(not 0 <= p <= 100 for p in (n.loss_pct, n.reorder_pct, n.duplicate_pct)):
        raise ValueError("Loss, reorder and duplicate are 0 to 100 %")
    if n.reorder_pct and not n.delay_ms:
        raise ValueError("Reorder needs a delay")
    if n.distribution != "uniform" and n.distribution not in caps.distributions:
        raise ValueError(f"{router_name} has no {n.distribution} table (/usr/lib/tc)")
    parts = []
    if n.delay_ms:
        parts.append(f"delay {n.delay_ms}ms")
        if n.jitter_ms:
            parts.append(f"{n.jitter_ms}ms")
            if n.distribution != "uniform":
                parts.append(f"distribution {n.distribution}")
    for name, pct in (("loss", n.loss_pct), ("reorder", n.reorder_pct), ("duplicate", n.duplicate_pct)):
        if pct:
            parts.append(f"{name} {pct:g}%")
    if not parts:
        raise ValueError("Nothing to impair: set a delay, loss, reorder or duplicate")
    return " ".join(parts)


def _netem(
    req: FaultRequest, t: FaultTarget, caps: FaultCaps, qdiscs: Sequence[Qdisc], router_name: str
) -> CompiledFault:
    n = req.netem or NetemParams()
    if not caps.netem:
        raise ValueError(f"{router_name} has no netem (sch_netem)")
    params = _netem_params(n, caps, router_name)
    dev = t.device
    if not dev:
        raise ValueError(f"Cannot tell which port of br-lan leads to {_who(t)}")
    if not t.ip:
        raise ValueError(f"No IPv4 address known for {t.mac}; enter one")
    commands: list[str] = []
    clear: list[str] = []
    on_dev = [q for q in qdiscs if q.dev == dev]
    if n.direction in ("to", "both"):
        root = next((q for q in on_dev if q.root), None)
        if root is not None and root.handle == APP_ROOT:
            raise ValueError(f"{dev} already has a netem fault; clear it first.")
        if root is not None and not (root.kind in KERNEL_DEFAULTS and root.handle == "0:"):
            raise ValueError(
                f"{dev} has a traffic-control qdisc from someone else ({root.kind} {root.handle}); "
                "netem would replace it."
            )
        if caps.band is None:
            raise ValueError(
                f"{router_name} has neither sch_prio nor sch_ets, so netem cannot be kept to the target's "
                "traffic; use from target"
            )
        band = (
            f"prio bands 4 priomap {PRIOMAP}"
            if caps.band == "prio"
            else f"ets bands 4 strict 4 priomap {PRIOMAP}"
        )
        commands += [
            f"tc qdisc add dev {dev} root handle {APP_ROOT} {band}",
            f"tc qdisc add dev {dev} parent {APP_ROOT}4 handle 1ee8: netem {params}",
            f"tc filter add dev {dev} parent {APP_ROOT} protocol ip prio 1 u32 "
            f"match ip dst {t.ip}/32 flowid {APP_ROOT}4",
        ]
        clear.append(f"tc qdisc del dev {dev} root")
    if n.direction in ("from", "both"):
        if not caps.ifb:
            raise ValueError(f"{router_name} has no ifb module: netem from the target is not possible here")
        if any(q.dev == APP_IFB for q in qdiscs):
            raise ValueError(f"{APP_IFB} already carries a netem fault from a target; clear it first.")
        ingress = next((q for q in on_dev if q.kind == "ingress"), None)
        if ingress is not None:
            raise ValueError(
                f"{dev} has a traffic-control qdisc from someone else (ingress {ingress.handle}); "
                "netem would replace it."
            )
        commands += [
            f"ip link add {APP_IFB} type ifb",
            f"ip link set {APP_IFB} up",
            f"tc qdisc add dev {dev} handle ffff: ingress",
            f"tc filter add dev {dev} parent ffff: protocol ip prio 1 u32 match ip src {t.ip}/32 "
            f"action mirred egress redirect dev {APP_IFB}",
            f"tc qdisc add dev {APP_IFB} root handle 1ee9: netem {params}",
        ]
        clear += [f"tc qdisc del dev {dev} ingress", f"ip link del {APP_IFB}"]
    return CompiledFault(
        (),
        tuple(commands),
        (),
        tuple(clear),
        f"netem {n.direction} {_who(t)}: {params}",
        dev,
        req.hold_s,
        True,
    )


def compile_fault(
    req: FaultRequest,
    target: FaultTarget,
    caps: FaultCaps,
    ports: PortsState | None,
    qdiscs: Sequence[Qdisc],
    armed: Sequence[ArmedFault],
    rtp: Sequence[int],
    router_name: str,
    *,
    id: str,
) -> CompiledFault:
    if req.hold_s is not None and not HOLD_MIN <= req.hold_s <= HOLD_MAX:
        raise ValueError(f"Hold for {HOLD_MIN} to {HOLD_MAX} s")
    if req.kind in ("isolate", "block"):
        return _nft(req, target, caps, rtp, id)
    if req.kind == "netem":
        return _netem(req, target, caps, qdiscs, router_name)
    if req.kind == "link_down":
        if target.via not in (None, "wired"):
            raise ValueError(
                "A switch port cannot disconnect a Wi-Fi station. For Wi-Fi use Deauth or AP down."
            )
        if ports is None or not ports.managed:
            raise ValueError("This router's switch is not managed by swconfig")
        if req.port is None:
            raise ValueError(
                f"Pick the port {_who(target)} is plugged into (the switch does not list its MAC)"
            )
        down = enable_commands(ports, req.port, False, router_name)  # the own-port refusals
        label = next((p.label for p in ports.ports if p.num == req.port), f"port {req.port}")
        if not down:
            raise ValueError(f"{label} is off already")
        up = [f"swconfig dev {ports.switch} port {req.port} set enable 1"]  # whatever the port is now
        return CompiledFault(
            (), tuple(down), (), tuple(up), f"Link down {label} ({_who(target)})", None, req.hold_s, True
        )
    ifname = _station(target)
    mac = target.mac or ""
    if req.kind == "deauth":
        return CompiledFault(
            (), (del_client_command(ifname, mac, 0),), (), (), f"Deauth {_who(target)}", ifname, None, False
        )
    if req.kind == "ban":
        seconds = req.ban_s or 0
        if not BAN_MIN <= seconds <= BAN_MAX:
            raise ValueError(f"Block for {BAN_MIN} to {BAN_MAX} seconds")
        command = del_client_command(ifname, mac, seconds * 1000)
        return CompiledFault(
            (), (command,), (), (), f"Block {_who(target)} for {seconds} s", ifname, seconds, True
        )
    return CompiledFault(
        (),
        (f"hostapd_cli -i {ifname} disable",),
        (),
        (f"hostapd_cli -i {ifname} enable",),
        f"AP down {ifname}",
        ifname,
        req.hold_s,
        True,
    )
