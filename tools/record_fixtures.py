"""Record a router's read-only probe output into tests/fixtures/<name>/commands.json.

Read-only: it sends only the probe command set and refuses any other host than AP2
(192.168.1.2) unless --allow-other is given. Secrets are replaced before writing.

    uv run python tools/record_fixtures.py --host 192.168.1.2 \
        --identity C:/Essence_SC/home/.ssh/id_rsa --out tests/fixtures/ap2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

from openwrtgui.probe.commands import DESCRIBE_COMMANDS, STATUS_COMMANDS, wireless_validate
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key

AP2 = "192.168.1.2"
ALLOWED = (*DESCRIBE_COMMANDS, *STATUS_COMMANDS, wireless_validate("radio0"))
_SECRET_JSON = re.compile(r'("(?:key|password|pincode)"\s*:\s*)"[^"]*"')
_IMEI = re.compile(r"\b\d{15}\b")


def sanitize(text: str) -> str:
    return _IMEI.sub("<imei>", _SECRET_JSON.sub(r'\1"<hidden>"', text))


async def record(host: str, identity: Path, known_hosts: Path) -> dict[str, dict[str, object]]:
    info = await fetch_host_key(host)
    print(f"{host} host key {info.type} {info.fingerprint}")
    keys = HostKeyStore(known_hosts)
    keys.pin(host, 22, info)
    t = await SshTransport.connect(host, 22, "root", host_keys=keys, key_paths=[identity])
    recorded: dict[str, dict[str, object]] = {}
    try:
        for command in ALLOWED:
            r = await t.run(command)
            entry: dict[str, object] = {"stdout": sanitize(r.stdout), "exit": r.exit_status}
            if r.stderr:
                entry["stderr"] = sanitize(r.stderr)
            recorded[command] = entry
    finally:
        await t.close()
    return recorded


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=AP2)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-other", action="store_true")
    args = ap.parse_args(argv)
    if args.host != AP2 and not args.allow_other:
        print(f"refusing {args.host}: only AP2 ({AP2}) without --allow-other", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        recorded = asyncio.run(record(args.host, args.identity, Path(tmp) / "known_hosts"))
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "commands.json"
    target.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(recorded)} recordings to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
