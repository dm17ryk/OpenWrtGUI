"""Offline: the as-found check of the access tests leaves out carrier-assigned listeners (HW-3, 2026-11-13:
after the restore's reboot dnsmasq listened on a new LTE address, and only that "differed")."""

from __future__ import annotations

from test_ap2_access import fixed_addresses, stable_listeners

NETWORK = (
    "network.loopback=interface\nnetwork.loopback.ipaddr='127.0.0.1'\n"
    "network.lan=interface\nnetwork.lan.ipaddr='192.168.1.2/24'\nnetwork.lan.ip6assign='60'\n"
    "network.lte=interface\nnetwork.lte.proto='qmi'\n"
)
BEFORE = {("0.0.0.0", 22), ("::", 22), ("127.0.0.1", 53), ("192.168.1.2", 53), ("100.64.0.5", 53)}


def test_fixed_addresses_come_from_the_network_config() -> None:
    assert fixed_addresses(NETWORK) == {"127.0.0.1", "192.168.1.2"}


def test_a_new_carrier_address_is_not_a_difference() -> None:
    fixed = fixed_addresses(NETWORK)
    after = (BEFORE - {("100.64.0.5", 53)}) | {("100.64.0.9", 53)}
    assert stable_listeners(after, fixed) == stable_listeners(BEFORE, fixed)
    assert ("192.168.1.2", 53) in stable_listeners(BEFORE, fixed)


def test_a_listener_gone_from_a_fixed_address_still_differs() -> None:
    fixed = fixed_addresses(NETWORK)
    assert stable_listeners(BEFORE - {("192.168.1.2", 53)}, fixed) != stable_listeners(BEFORE, fixed)
    assert stable_listeners(BEFORE - {("0.0.0.0", 22)}, fixed) != stable_listeners(BEFORE, fixed)
