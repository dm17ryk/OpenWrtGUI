"""v0.6c Access parsers: dropbear, uhttpd, listeners, the password policy (plan D2, D4, D6)."""

from __future__ import annotations

import pytest

from openwrtgui.system.access import (
    PasswordPolicy,
    check_password,
    parse_dropbear,
    parse_listeners,
    parse_policy,
    parse_uhttpd,
)

AP2_DROPBEAR = """dropbear.main=dropbear
dropbear.main.enable='1'
dropbear.main.PasswordAuth='on'
dropbear.main.RootPasswordAuth='on'
dropbear.main.Port='22'
"""

AP2_UHTTPD = """uhttpd.main=uhttpd
uhttpd.main.listen_http='0.0.0.0:80' '[::]:80'
uhttpd.main.listen_https='0.0.0.0:443' '[::]:443'
uhttpd.main.redirect_https='0'
uhttpd.main.home='/www'
"""


def test_dropbear_defaults() -> None:
    (main,) = parse_dropbear(AP2_DROPBEAR)
    assert main.section == "main"
    assert (main.enable, main.port, main.interface, main.direct_interface) == (True, 22, "", "")
    assert (main.password_auth, main.root_password_auth, main.gateway_ports) == (True, True, False)


def test_dropbear_second_instance_and_flags() -> None:
    text = AP2_DROPBEAR + (
        "dropbear.cfg0a1b2c=dropbear\n"
        "dropbear.cfg0a1b2c.Port='2222'\n"
        "dropbear.cfg0a1b2c.Interface='lan'\n"
        "dropbear.cfg0a1b2c.PasswordAuth='off'\n"
        "dropbear.cfg0a1b2c.GatewayPorts='1'\n"
        "dropbear.cfg0a1b2c.enable='0'\n"
    )
    main, extra = parse_dropbear(text)
    assert main.section == "main"
    assert (extra.section, extra.port, extra.interface) == ("cfg0a1b2c", 2222, "lan")
    assert (extra.enable, extra.password_auth, extra.root_password_auth, extra.gateway_ports) == (
        False,
        False,
        True,
        True,
    )


def test_uhttpd_luci_on_network() -> None:
    http = parse_uhttpd(AP2_UHTTPD)
    assert http.luci_on_network is True
    assert http.redirect_https is False
    assert http.listen_http == ("0.0.0.0:80", "[::]:80")
    assert http.loopback_kept is True

    off = parse_uhttpd(
        "uhttpd.main=uhttpd\n"
        "uhttpd.main.listen_http='127.0.0.1:80' '[::1]:80'\n"
        "uhttpd.main.listen_https='127.0.0.1:443' '[::1]:443'\n"
        "uhttpd.main.redirect_https='1'\n"
    )
    assert (off.luci_on_network, off.redirect_https, off.loopback_kept) == (False, True, True)

    custom = parse_uhttpd("uhttpd.main=uhttpd\nuhttpd.main.listen_http='192.168.1.2:80'\n")
    assert (custom.luci_on_network, custom.loopback_kept) == (None, False)


def test_listeners() -> None:
    text = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1945 1\n"
        "   1: 0100007F:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1408 1\n"
        "   4: 0201A8C0:0016 0A01A8C0:C081 01 00000024:00000000 01:00000014 00000000     0        0 18406 3\n"
        "  sl  local_address                         remote_address                        st tx_queue\n"
        "   0: 00000000000000000000000000000000:0050 00000000000000000000000000000000:0000 0A 00000000\n"
        "   5: 00000000000000000000000001000000:0035 00000000000000000000000000000000:0000 0A 00000000\n"
    )
    assert parse_listeners(text) == {("0.0.0.0", 80), ("127.0.0.1", 22), ("::", 80), ("::1", 53)}


def test_policy() -> None:
    assert parse_policy("rpcd.cfg01=rpcd\nrpcd.cfg01.timeout='30'\n") is None
    policy = parse_policy(
        "rpcd.policy=policy\nrpcd.policy.enabled='1'\nrpcd.policy.pw_length='8'\nrpcd.policy.digits='1'\n"
    )
    assert policy == PasswordPolicy(
        enabled=True, pw_length=8, digits=True, uc_lc=False, special_characters=False
    )
    check_password("Abcdefg1", policy)
    with pytest.raises(ValueError, match="the policy asks for a digit"):
        check_password("abcdefgh", policy)
    with pytest.raises(ValueError, match="at least 8 characters"):
        check_password("abc1", policy)
    off = parse_policy("rpcd.policy=policy\n")
    assert off == PasswordPolicy(
        enabled=False, pw_length=0, digits=False, uc_lc=False, special_characters=False
    )
    check_password("x", off)  # a disabled policy asks nothing


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("", "Type a password"),
        ("two\nlines", "one line"),
        ("nul\x00", "one line"),
        ("x" * 129, "at most 128"),
    ],
)
def test_password_refusals_without_a_policy(password: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        check_password(password, None)


def test_policy_case_and_special() -> None:
    policy = PasswordPolicy(enabled=True, pw_length=0, digits=False, uc_lc=True, special_characters=True)
    check_password("Abc!", policy)
    with pytest.raises(ValueError, match="upper and lower case"):
        check_password("abc!", policy)
    with pytest.raises(ValueError, match="a special character"):
        check_password("Abcd", policy)
