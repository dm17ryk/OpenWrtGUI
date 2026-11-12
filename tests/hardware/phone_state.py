"""The bench phone as its owner (the acoustic session) leaves it, read over adb before and after HW-2's on-air
tests (plan Task 17). Reads only: `dumpsys`, `settings get`, `cmd wifi status` and `list-suggestions`.

The owner's state: their app (its package given at run time, `--phone-app`) installed and untouched,
`stay_on_while_plugged_in` 2, the phone unlocked, no Wi-Fi network connected or suggested, and Wi-Fi on or off
as found.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

STAY_ON = "2"  # plugged in on USB and AC: the screen stays on
_LOCKED = re.compile(r"\b(?:mScreenLocked|mShowingLockscreen|isKeyguardShowing)=(true|false)\b")
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")


def reads(app: str) -> dict[str, str]:
    """The adb shell reads, by name. `app` is a package name, checked: it goes into a shell command."""
    if not _PACKAGE.fullmatch(app):
        raise ValueError(f"{app!r} is not an Android package name")
    return {
        "app": f"dumpsys package {app}",
        "stay_on": "settings get global stay_on_while_plugged_in",
        "locked": "dumpsys deviceidle",  # mScreenLocked (Android 10 and later)
        "wifi": "cmd wifi status",
        "suggestions": "cmd wifi list-suggestions",  # the shell's own suggestions, the only ones a test adds
    }


@dataclass(frozen=True)
class PhoneState:
    app: str | None  # the owner's app: its version code and last update time; None when not installed
    stay_on: str
    locked: bool | None  # None: the phone did not say
    wifi_enabled: bool
    connected: str | None  # the SSID it is connected to
    suggested: bool  # any network suggestion from the shell


def _app(text: str) -> str | None:
    version = re.search(r"\bversionCode=(\d+)", text)
    updated = re.search(r"\blastUpdateTime=(.+)", text)
    if version is None or updated is None:
        return None
    return f"versionCode={version.group(1)}, lastUpdateTime={updated.group(1).strip()}"


def parse_phone(outputs: Mapping[str, str]) -> PhoneState:
    locked = _LOCKED.search(outputs.get("locked", ""))
    wifi = outputs.get("wifi", "")
    connected = re.search(r'^Wifi is connected to "(.*)"$', wifi, re.M)
    suggestions = outputs.get("suggestions", "").strip()
    return PhoneState(
        app=_app(outputs.get("app", "")),
        stay_on=outputs.get("stay_on", "").strip(),
        locked=None if locked is None else locked.group(1) == "true",
        wifi_enabled="Wifi is enabled" in wifi,
        connected=connected.group(1) if connected else None,
        suggested=bool(suggestions) and not suggestions.startswith("No suggestions"),
    )


async def read_phone(serial: str, app: str) -> PhoneState:
    def shell(command: str) -> str:
        done = subprocess.run(
            ["adb", "-s", serial, "shell", command], capture_output=True, text=True, timeout=30, check=False
        )
        return done.stdout

    outputs = {name: await asyncio.to_thread(shell, command) for name, command in reads(app).items()}
    return parse_phone(outputs)


def _owner_end(state: PhoneState, app: str) -> list[str]:
    """What must hold whenever the phone is handed back."""
    problems = []
    if state.app is None:
        problems.append(f"{app} is not installed")
    if state.stay_on != STAY_ON:
        problems.append(f"stay_on_while_plugged_in is {state.stay_on or 'unset'}, not {STAY_ON}")
    if state.locked is not False:
        problems.append("the phone is locked" if state.locked else "the phone does not say it is unlocked")
    return problems


def start_problems(found: PhoneState, app: str) -> list[str]:
    """Before anything goes on air: a phone not as its owner described it is asked about, not used."""
    problems = _owner_end(found, app)
    if found.connected is not None:
        problems.append(f"Wi-Fi is connected to {found.connected}; its owner wants no network at the end")
    if found.suggested:
        problems.append("the phone already has a network suggestion from the shell")
    return problems


def as_found_problems(before: PhoneState, after: PhoneState, app: str) -> list[str]:
    """After the window: everything the owner asked for, and Wi-Fi on or off as found."""
    problems = [p for p in _owner_end(after, app) if not p.endswith("is not installed")]
    if after.app is None:
        problems.insert(0, f"{app} is not installed")
    elif after.app != before.app:
        problems.insert(0, f"{app} changed (version or update time)")
    if after.wifi_enabled != before.wifi_enabled:
        now, was = ("on", "off") if after.wifi_enabled else ("off", "on")
        problems.append(f"Wi-Fi is {now}; it was {was}")
    if after.connected is not None:
        problems.append(f"Wi-Fi is still connected to {after.connected}")
    if after.suggested:
        problems.append("a network suggestion is left on the phone")
    return problems
