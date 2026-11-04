import re

from openwrtgui.version import APP_VERSION, BASE_VERSION


def test_base_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", BASE_VERSION)


def test_app_version_starts_with_base() -> None:
    assert APP_VERSION.startswith(BASE_VERSION)
