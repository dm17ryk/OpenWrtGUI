"""Discovery compares the real values, then hides secret ones (v1.0b1 D3)."""

from __future__ import annotations

from openwrtgui.discovery.overlay import ConfigDiff, OptionChange
from openwrtgui.discovery.state import hide_secrets


def _diff(*changes: OptionChange) -> ConfigDiff:
    return ConfigDiff(config="wireless", first_boot=False, changes=changes)


def test_a_changed_key_stays_listed_with_both_sides_hidden() -> None:
    change = OptionChange(key="wireless.default_radio0.key", image="image-key", router="router-key")
    (diff,) = hide_secrets([_diff(change)])
    assert diff.changes == (
        OptionChange(key="wireless.default_radio0.key", image="<hidden>", router="<hidden>"),
    )


def test_a_key_on_one_side_only_keeps_none() -> None:
    (diff,) = hide_secrets(
        [_diff(OptionChange(key="wireless.wifinet1.sae_password", image=None, router="x"))]
    )
    assert (diff.changes[0].image, diff.changes[0].router) == (None, "<hidden>")


def test_other_options_are_shown_as_they_are() -> None:
    change = OptionChange(key="wireless.default_radio0.ssid", image="OpenWrt", router="Bench")
    first_boot = ConfigDiff(config="network", first_boot=True, changes=())
    assert hide_secrets([_diff(change), first_boot]) == (_diff(change), first_boot)
