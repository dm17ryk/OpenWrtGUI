"""Which shell commands are safe to run while a harness owns the bench (read-only)."""

from __future__ import annotations

import re
import shlex

from openwrtgui.discovery.commands import OVERLAY_LS, ROM_LS
from openwrtgui.lte.commands import TTY_LIST
from openwrtgui.system.commands import BACKUP_SIZE, HAS_BLOCK, PASSWORD_DIGEST

# "&" also covers "&&" and "|&": a single & starts a second command in the background.
_FORBIDDEN = (";", "&", "||", ">", "<", "`", "$(", "\n")
# Discovery's own reads (v0.5), as exact texts: they need `-exec ls` and a stderr redirect. The System
# screen's backup size (v0.6b): the archive goes to wc only, nothing is written on the router. Its
# block-mount probe and password digest (v0.6c): `test` and `awk` are not open programs here.
_EXACT = frozenset({OVERLAY_LS, ROM_LS, TTY_LIST, BACKUP_SIZE, HAS_BLOCK, PASSWORD_DIGEST})
_FIRMWARE_HASH = re.compile(
    r"dd if=/dev/mtdblock\d{1,2} bs=65536 count=\d{1,6} 2>/dev/null \| head -c \d{1,10} \| sha256sum"
)
# the LTE screen's modem reads (lte/commands.py): serving system, signal, operating mode; not the IMEI
_UQMI_READ = re.compile(
    r"uqmi -s -d /dev/cdc-wdm[0-9] -t 2000 --get-(serving-system|signal-info|device-operating-mode)"
)

_ALWAYS = frozenset(
    [
        "cat",
        "head",
        "tail",
        "grep",
        "wc",
        "df",
        "free",
        "uptime",
        "uname",
        "ps",
        "ifstatus",
        "jsonfilter",
        "cut",
        "tr",
        "md5sum",
        "sha256sum",
        "which",
        "hexdump",
        "ls",  # lists names only (v0.6c: repository keys, network devices)
    ]
)
_UCI_READ = frozenset({"show", "get", "changes", "export"})
_UBUS_READ_METHODS = frozenset(
    [
        "status",
        "info",
        "board",
        "dump",
        "get",
        "list",
        "getFeatures",
        "getBoardJSON",
        "getDHCPLeases",
        "getHostHints",
        "getNetworkDevices",
        "getWirelessDevices",
        "assoclist",
        "freqlist",
        "txpowerlist",
        "countrylist",
        "get_validate",
        "get_proto_handlers",
        "getTimezones",  # the System screen's time zone list (LuCI's own read)
        "getLEDs",  # the LEDs tab (v0.6c, LuCI's own read)
    ]
)
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir"})
_IP_OBJECTS = frozenset({"addr", "address", "link", "route", "neigh", "rule"})
_CHANGE_WORDS = frozenset(
    {"add", "del", "delete", "set", "flush", "change", "replace", "append", "prepend", "restore"}
)
# iw is allow-listed: it has many verbs that change the radio (switch, offchannel, vendor, scan, ...).
_IW_TOP = frozenset({"list", "event", "help", "--version"})
_IW_ON_DEVICE = (["info"], ["link"], ["channels"], ["get"])
_IW_ON_DEVICE_PAIRS = (
    ["station", "dump"],
    ["station", "get"],
    ["survey", "dump"],
    ["scan", "dump"],
    ["mpath", "dump"],
    ["reg", "get"],
)
# Options taking a value, and options allowed at all, for the programs with argument rules.
_LOGREAD_OPTIONS = {"-f": False, "-t": False, "-z": False, "-l": True, "-e": True, "-s": True}
_DMESG_OPTIONS = {"-r": False, "-T": False, "-s": True}
_DATE_OPTIONS = frozenset({"-u", "-R", "-I", "--utc"})
_UNIQ_VALUE_OPTIONS = frozenset({"-f", "-s", "-w"})


def _options_ok(args: list[str], allowed: dict[str, bool], operands: bool) -> bool:
    """Every option is in `allowed` (value: takes an argument); bare operands only when `operands`."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and len(arg) > 1:
            option = arg[:2]
            if option not in allowed:
                return False
            if allowed[option] and len(arg) == 2:
                i += 1
        elif not operands:
            return False
        i += 1
    return True


def _sort_ok(args: list[str]) -> bool:
    # -o FILE / --output writes a file; --compress-program runs a program.
    for arg in args:
        if arg.startswith(("--output", "--compress-program")):
            return False
        if arg.startswith("-") and not arg.startswith("--") and "o" in arg:
            return False
    return True


def _uniq_ok(args: list[str]) -> bool:
    # uniq [INPUT [OUTPUT]]: a second operand is written to.
    operands: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in _UNIQ_VALUE_OPTIONS:
            skip = True
        elif not arg.startswith("-"):
            operands.append(arg)
    return len(operands) <= 1


def _iw_ok(args: list[str]) -> bool:
    words = [a for a in args if not (a.startswith("-") and a != "--version")]
    if not words or words[0] in _IW_TOP:
        return True
    if words[0] == "reg":
        return words[1:] == ["get"]
    if words[0] in ("dev", "phy"):
        rest = words[2:]
        if len(words) == 1:
            return True
        return rest[:1] in _IW_ON_DEVICE or rest[:2] in _IW_ON_DEVICE_PAIRS
    return False


def _segment_ok(words: list[str]) -> bool:
    if not words:
        return False
    prog, args = words[0], words[1:]
    if prog in _ALWAYS:
        return True
    if prog == "sort":
        return _sort_ok(args)
    if prog == "uniq":
        return _uniq_ok(args)
    if prog == "date":
        # Any operand or -s/--set sets the clock; formats (+...) and display options only.
        return all(a.startswith("+") or a in _DATE_OPTIONS or a.startswith("-I") for a in args)
    if prog == "logread":
        return _options_ok(args, _LOGREAD_OPTIONS, operands=False)
    if prog == "dmesg":
        return _options_ok(args, _DMESG_OPTIONS, operands=False)
    if prog == "iwinfo":
        return "scan" not in args
    if prog == "awk":
        # awk can run programs (system, getline from a command) and write files (print > f).
        return not any(word in a for a in args for word in ("system", "getline"))
    if prog == "find":
        return not any(a in _FIND_ACTIONS or a.startswith(("-fprint", "-fls")) for a in args)
    if prog == "top":
        return any(a.startswith("-b") for a in args)
    if prog == "uci":
        verbs = [a for a in args if not a.startswith("-")]
        return bool(verbs) and verbs[0] in _UCI_READ
    if prog == "ubus":
        verbs = [a for a in args if not a.startswith("-")]
        if verbs[:1] == ["list"]:
            return True
        return len(verbs) >= 3 and verbs[0] == "call" and verbs[2] in _UBUS_READ_METHODS
    if prog == "nft":
        verbs = [a for a in args if not a.startswith("-")]
        return verbs[:1] == ["list"]
    if prog == "tc":
        return "show" in args and not (_CHANGE_WORDS & set(args))
    if prog == "ip":
        verbs = [a for a in args if not a.startswith("-")]
        return bool(verbs) and verbs[0] in _IP_OBJECTS and not (_CHANGE_WORDS & set(verbs[1:]))
    if prog == "iw":
        return _iw_ok(args)
    if prog == "swconfig":
        return bool({"show", "get", "list"} & set(args)) and "set" not in args
    if prog in ("apk", "opkg"):
        return args[:1] in (["list"], ["info"])
    if prog == "sysupgrade":
        return args == ["-l"]
    return False


def is_read_only_command(cmd: str) -> bool:
    if cmd in _EXACT or _FIRMWARE_HASH.fullmatch(cmd) or _UQMI_READ.fullmatch(cmd):
        return True
    if not cmd.strip() or any(token in cmd for token in _FORBIDDEN):
        return False
    try:
        segments = [shlex.split(part) for part in cmd.split("|")]
    except ValueError:
        return False
    return all(_segment_ok(words) for words in segments)
