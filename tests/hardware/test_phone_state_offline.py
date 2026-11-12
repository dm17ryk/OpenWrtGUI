"""The bench phone's owner checks for HW-2 (plan Task 17), checked offline (no hardware marker): the phone is
read before and after the on-air tests, and anything not as its owner left it is named. The owner's app is
given at run time (`--phone-app`); a made-up package stands in for it here."""

from __future__ import annotations

from phone_state import PhoneState, as_found_problems, parse_phone, reads, start_problems

APP = "com.example.ownerapp"
APP_DUMP = (
    f"Packages:\n  Package [{APP}] (3c1e2f0):\n    versionCode=412 minSdk=26 targetSdk=33\n"
    "    versionName=4.1.2\n    firstInstallTime=2026-10-01 09:12:44\n"
    "    lastUpdateTime=2026-11-02 14:03:10\n"
)
WIFI_IDLE = (
    "Wifi is enabled\nWifi scanning is always available\n==== Primary ClientModeManager instance ====\n"
    "Wifi is not connected\n"
)
WIFI_ON_TEST = (
    "Wifi is enabled\nWifi scanning is always available\n==== Primary ClientModeManager instance ====\n"
    'Wifi is connected to "OwgTest"\nWifiInfo: SSID: "OwgTest", BSSID: 02:00:00:00:00:01\n'
)
UNLOCKED = "  mScreenOn=true\n  mScreenLocked=false\n"


def _outputs(**changed: str) -> dict[str, str]:
    base = {
        "app": APP_DUMP,
        "stay_on": "2\n",
        "locked": UNLOCKED,
        "wifi": WIFI_IDLE,
        "suggestions": "No suggestions on this device\n",
    }
    return base | changed


def test_the_reads_name_the_app_given_at_run_time() -> None:
    assert reads(APP)["app"] == f"dumpsys package {APP}"
    assert set(reads(APP)) == {"app", "stay_on", "locked", "wifi", "suggestions"}


def test_parse_the_phone_as_its_owner_leaves_it() -> None:
    state = parse_phone(_outputs())
    assert state == PhoneState(
        app="versionCode=412, lastUpdateTime=2026-11-02 14:03:10",
        stay_on="2",
        locked=False,
        wifi_enabled=True,
        connected=None,
        suggested=False,
    )
    assert start_problems(state, APP) == []
    assert as_found_problems(state, state, APP) == []


def test_parse_what_the_owner_does_not_want_left() -> None:
    state = parse_phone(
        _outputs(
            app=f"Unable to find package: {APP}\n",
            stay_on="0\n",
            locked="  mScreenOn=false\n  mScreenLocked=true\n",
            wifi=WIFI_ON_TEST,
            suggestions='SSID: "OwgTest", isAppInteractionRequired: false\n',
        )
    )
    assert state.app is None and state.stay_on == "0" and state.locked is True
    assert state.connected == "OwgTest" and state.suggested


def test_a_phone_that_does_not_say_whether_it_is_locked() -> None:
    assert parse_phone(_outputs(locked="")).locked is None


def test_problems_after_the_window_name_each_change() -> None:
    before = parse_phone(_outputs())
    after = parse_phone(
        _outputs(
            app=APP_DUMP.replace("lastUpdateTime=2026-11-02 14:03:10", "lastUpdateTime=2026-11-13 10:00:00"),
            stay_on="0\n",
            locked="",
            wifi="Wifi is disabled\n",
            suggestions='SSID: "OwgTest"\n',
        )
    )
    assert as_found_problems(before, after, APP) == [
        f"{APP} changed (version or update time)",
        "stay_on_while_plugged_in is 0, not 2",
        "the phone does not say it is unlocked",
        "Wi-Fi is off; it was on",
        "a network suggestion is left on the phone",
    ]
    connected = parse_phone(_outputs(wifi=WIFI_ON_TEST))
    assert as_found_problems(before, connected, APP) == ["Wi-Fi is still connected to OwgTest"]
    gone = parse_phone(_outputs(app=f"Unable to find package: {APP}\n"))
    assert as_found_problems(before, gone, APP) == [f"{APP} is not installed"]


def test_a_phone_not_as_its_owner_said_is_not_used() -> None:
    """Before anything goes on air: the owner's state is the baseline, so a different start is asked about."""
    found = parse_phone(_outputs(wifi=WIFI_ON_TEST.replace("OwgTest", "SomeNet"), stay_on="0\n"))
    assert start_problems(found, APP) == [
        "stay_on_while_plugged_in is 0, not 2",
        "Wi-Fi is connected to SomeNet; its owner wants no network at the end",
    ]
