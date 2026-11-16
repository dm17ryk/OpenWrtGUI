"""The LTE settings' own rules, before any request reaches the router (v1.0b2 D11)."""

from __future__ import annotations

import pytest

from openwrtgui.lte.settings import LteSettings, settings_request


def test_the_metric_is_bounded_in_the_domain_too() -> None:
    """v0.6a minor (#28): netifd's metric is unsigned 32-bit; the API model checks it, and so does the
    domain."""
    for metric in (-1, 4_294_967_296):
        with pytest.raises(ValueError, match="^The metric is a whole number from 0 to 4294967295$"):
            settings_request("lte", LteSettings(metric=metric))
    assert settings_request("lte", LteSettings(metric=4_294_967_295)).edits[0].value == "4294967295"
