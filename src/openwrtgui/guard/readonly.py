"""Which shell commands are safe to run while a harness owns the bench (read-only)."""

from __future__ import annotations

import shlex

_FORBIDDEN = (";", "&&", "||", ">", "<", "`", "$(", "\n")

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
        "date",
        "dmesg",
        "logread",
        "ps",
        "ifstatus",
        "iwinfo",
        "jsonfilter",
        "sort",
        "uniq",
        "cut",
        "tr",
        "md5sum",
        "sha256sum",
        "which",
        "hexdump",
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
    ]
)
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"})
_IP_OBJECTS = frozenset({"addr", "address", "link", "route", "neigh", "rule"})
_CHANGE_WORDS = frozenset({"add", "del", "delete", "set", "flush", "change", "replace"})
_IW_CHANGE_WORDS = frozenset({"set", "del", "add", "connect", "disconnect", "join", "leave"})


def _segment_ok(words: list[str]) -> bool:
    if not words:
        return False
    prog, args = words[0], words[1:]
    if prog in _ALWAYS:
        return True
    if prog == "awk":
        # awk can run programs (system, getline from a command) and write files (print > f).
        return not any(word in a for a in args for word in ("system", "getline"))
    if prog == "find":
        return not any(a in _FIND_ACTIONS for a in args)
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
        if _IW_CHANGE_WORDS & set(args):
            return False
        return not ("scan" in args and "trigger" in args)
    if prog == "swconfig":
        return bool({"show", "get", "list"} & set(args)) and "set" not in args
    if prog in ("apk", "opkg"):
        return args[:1] in (["list"], ["info"])
    return False


def is_read_only_command(cmd: str) -> bool:
    if not cmd.strip() or any(token in cmd for token in _FORBIDDEN):
        return False
    try:
        segments = [shlex.split(part) for part in cmd.split("|")]
    except ValueError:
        return False
    return all(_segment_ok(words) for words in segments)
