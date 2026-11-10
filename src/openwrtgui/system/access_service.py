"""System › Access, LEDs and Mount points (v0.6c plan): reads first; each write comes with its task. Kept
apart from SystemService so that file stays small. Every read is its own exec; a part that fails is named."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

import asyncssh
from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.audit import AuditLog, mask
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.net.apply import (
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    net_plan,
    saved_check,
)
from openwrtgui.net.commands import INTERFACE_DUMP
from openwrtgui.net.parse import parse_interface_dump
from openwrtgui.probe.commands import ROOT_PASSWORD_STATE
from openwrtgui.store.keys import AppKey
from openwrtgui.store.routers import RouterRecord, RouterStore, router_key_paths
from openwrtgui.store.settings import SettingsStore
from openwrtgui.system import commands as s
from openwrtgui.system.access import (
    HttpState,
    PasswordPolicy,
    RepoKey,
    SshInstance,
    check_password,
    parse_dropbear,
    parse_listeners,
    parse_policy,
    parse_uhttpd,
    policy_ops,
)
from openwrtgui.system.leds import LedInfo, LedRow, parse_led_sections, parse_leds
from openwrtgui.system.mounts import Mount, Usage, parse_df, parse_mounts
from openwrtgui.system.sshkeys import KeyLabel, label, parse_authorized_keys
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)

SCREEN = "System"


class SshKeyRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int  # the line in authorized_keys
    type: str | None  # None: a line that is not a key (kept as written)
    comment: str
    options: str | None
    fingerprint: str | None
    label: KeyLabel
    owner: str | None
    text: str  # the line itself: a public key


class AccessState(BaseModel):
    model_config = ConfigDict(frozen=True)

    password: Literal["set", "none"] | None
    policy: PasswordPolicy | None  # None: the router has no rpcd.policy section
    ssh: list[SshInstance]
    app_instance: str | None  # the dropbear instance this app connects through
    app_interface: str | None  # the interface holding the address the app uses
    keys: list[SshKeyRow]
    http: HttpState
    https_served: bool  # something listens on uhttpd's HTTPS port (AP2: no)
    repo_keys: list[RepoKey]
    missing: tuple[str, ...]


class LedState(BaseModel):
    model_config = ConfigDict(frozen=True)

    leds: list[LedInfo]
    rows: list[LedRow]
    devices: list[str]
    missing: tuple[str, ...]


class MountState(BaseModel):
    model_config = ConfigDict(frozen=True)

    mounts: list[Mount]
    usage: list[Usage]
    block: bool  # block-mount is installed (fstab editing needs it, D8)


def _key_fingerprint(path: Path) -> str | None:
    """The fingerprint of a key file the app logs in with: its .pub, else the private key (no passphrase)."""
    try:
        pub = Path(f"{path}.pub")
        if pub.exists():
            return str(asyncssh.import_public_key(pub.read_text(encoding="utf-8")).get_fingerprint("sha256"))
        return str(asyncssh.read_private_key(str(path)).get_fingerprint("sha256"))
    except (OSError, ValueError, asyncssh.KeyImportError) as exc:
        log.info("cannot read the fingerprint of %s: %s", path, exc)
        return None


def https_ports(http: HttpState) -> set[int]:
    ports: set[int] = set()
    for entry in http.listen_https:
        port = entry.rsplit(":", 1)[-1]
        if port.isdigit():
            ports.add(int(port))
    return ports


def app_instance(instances: list[SshInstance], port: int, interface: str | None) -> SshInstance | None:
    """The enabled instance on the router's port that listens on every interface or on the app's one."""
    return next(
        (i for i in instances if i.enable and i.port == port and i.interface in ("", interface)), None
    )


class AccessService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        runner: ApplyRunner,
        settings: SettingsStore,
        app_key: AppKey,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._runner = runner
        self._settings = settings
        self._app_key = app_key

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _transport(self, router_id: str) -> tuple[RouterRecord, Transport]:
        rec = self._record(router_id)
        return rec, await self._pool.get(rec)

    def app_fingerprints(self, rec: RouterRecord) -> set[str]:
        """The keys this app logs in to `rec` with (its own key, or the router's key file)."""
        found = {self._app_key.fingerprint}
        for path in router_key_paths(rec, self._app_key.private_path):
            fingerprint = _key_fingerprint(path)
            if fingerprint is not None:
                found.add(fingerprint)
        return found

    def known_keys(self) -> dict[str, str]:
        return {k.fingerprint: k.owner for k in self._settings.load().known_keys}

    async def _app_interface(self, t: Transport, host: str, missing: list[str]) -> str | None:
        dump = await t.run(INTERFACE_DUMP)
        if not dump.ok:
            missing.append("interfaces")
            return None
        try:
            live = parse_interface_dump(json.loads(dump.stdout))
        except ValueError:
            missing.append("interfaces")
            return None
        return next((i.name for i in live if any(a.ip == host for a in i.ipv4)), None)

    def key_rows(self, rec: RouterRecord, text: str) -> list[SshKeyRow]:
        app, known = self.app_fingerprints(rec), self.known_keys()
        rows: list[SshKeyRow] = []
        for line in parse_authorized_keys(text):
            kind, owner = label(line.fingerprint, app, known)
            rows.append(SshKeyRow(**line.model_dump(), label=kind, owner=owner))
        return rows

    async def access(self, router_id: str) -> AccessState:
        rec, t = await self._transport(router_id)
        missing: list[str] = []

        async def read(command: str, name: str) -> str:
            result = await t.run(command)
            if not result.ok:
                missing.append(name)
                return ""
            return result.stdout

        state = (await read(ROOT_PASSWORD_STATE, "password state")).strip()
        dropbear = parse_dropbear(await read(s.UCI_DROPBEAR, "dropbear"))
        http = parse_uhttpd(await read(s.UCI_UHTTPD, "uhttpd"))
        policy = parse_policy(await read(s.UCI_RPCD, "rpcd"))
        listening = parse_listeners(await read(s.LISTENERS, "listeners"))
        interface = await self._app_interface(t, rec.host, missing)
        keys = await t.run(s.KEYS_READ)  # no file: no keys (dropbear's own default), not a failed read
        if not keys.ok and "No such file" not in keys.stderr:
            missing.append("authorized keys")
        repo: list[RepoKey] = []
        found_dir = False
        for command, kind in ((s.APK_KEYS, "apk"), (s.OPKG_KEYS, "opkg")):
            listed = await t.run(command)
            if listed.ok:
                found_dir = True
                repo += [RepoKey(name=n, kind=kind) for n in listed.stdout.split()]  # type: ignore[arg-type]
        if not found_dir:
            missing.append("repository keys")
        served = https_ports(http) & {port for _, port in listening}
        mine = app_instance(dropbear, rec.port, interface)
        return AccessState(
            password=state if state in ("set", "none") else None,  # type: ignore[arg-type]
            policy=policy,
            ssh=dropbear,
            app_instance=mine.section if mine else None,
            app_interface=interface,
            keys=self.key_rows(rec, keys.stdout if keys.ok else ""),
            http=http,
            https_served=bool(served),
            repo_keys=repo,
            missing=tuple(missing),
        )

    # ---------------------------------------------------------------- password and policy (D2)
    def _password_plan(self, rec: RouterRecord) -> NetPlan:
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[s.PASSWD],
            warnings=[
                f"LuCI and SSH password logins on {rec.name} use the new password. The app logs in with "
                f"its key and is not affected. A script that logs in to {rec.name} with the old password "
                "stops working."
            ],
        )

    async def plan_password(self, router_id: str) -> NetPlan:
        return self._password_plan(self._record(router_id))

    async def _digest(self, t: Transport) -> str | None:
        """A digest of root's hash: compared here, never logged or returned."""
        result = await t.run(s.PASSWORD_DIGEST)
        return result.stdout.split()[0] if result.ok and result.stdout.split() else None

    async def apply_password(self, router_id: str, password: str, digest: str | None) -> NetApplyResult:
        """`passwd root` with the password twice on stdin; proof: root's hash changed. The password is in no
        command line, plan, audit line, result or error."""
        rec, t = await self._transport(router_id)
        check_password(password, parse_policy(await self._stdout(t, s.UCI_RPCD)))
        plan = self._password_plan(rec)
        self._guard.require_clear()
        if digest != plan.digest:
            raise PreviewChanged(rec.name)
        async with self._pool.write_lock(rec.id):
            t = await self._pool.get(rec)
            before = await self._digest(t)
            result = await run_audited(
                t,
                s.PASSWD,
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                secrets=(password,),
                stdin=f"{password}\n{password}\n",
            )
            if not result.ok:
                reason = mask(
                    (result.stderr or result.stdout).strip() or f"exit {result.exit_status}", (password,)
                )
                error = f"The router refused the new password: {reason}"
                return NetApplyResult(rec.id, False, False, (), error, rec.host)
            after = await self._digest(t)
        changed = after is not None and after not in (before, s.EMPTY_DIGEST)
        detail = (
            "the router's password hash changed" if changed else "the router's password hash did not change"
        )
        return NetApplyResult(rec.id, True, changed, (NetCheck("password", changed, detail),), None, rec.host)

    async def _policy_plan(
        self, rec: RouterRecord, t: Transport, policy: PasswordPolicy
    ) -> tuple[NetPlan, dict[str, str]]:
        current = parse_uci_show(await self._stdout(t, s.UCI_RPCD))
        ops = policy_ops(current, policy)
        plan = net_plan(router_id=rec.id, screen=SCREEN, config="rpcd", ops=ops, current=current)
        return plan, current

    async def plan_policy(self, router_id: str, policy: PasswordPolicy) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._policy_plan(rec, t, policy))[0]

    async def apply_policy(
        self, router_id: str, policy: PasswordPolicy, digest: str | None
    ) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, current = await self._policy_plan(rec, t, policy)

            async def verify(t2: Transport) -> list[NetCheck]:
                return [await saved_check(t2, s.UCI_RPCD, plan.ops, current)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def _stdout(self, t: Transport, command: str) -> str:
        result = await t.run(command)
        return result.stdout if result.ok else ""

    async def leds(self, router_id: str) -> LedState:
        _rec, t = await self._transport(router_id)
        missing: list[str] = []
        leds = await t.run(s.LEDS)
        if not leds.ok:
            missing.append("LEDs (LuCI's rpcd plugin)")
        system = await t.run(s.UCI_SYSTEM)
        if not system.ok:
            missing.append("system config")
        devices = await t.run(s.NET_DEVICES)
        return LedState(
            leds=parse_leds(leds.stdout) if leds.ok else [],
            rows=parse_led_sections(system.stdout) if system.ok else [],
            devices=devices.stdout.split() if devices.ok else [],
            missing=tuple(missing),
        )

    async def mounts(self, router_id: str) -> MountState:
        _rec, t = await self._transport(router_id)
        mounts, usage = await t.run(s.MOUNTS), await t.run(s.DF)
        return MountState(
            mounts=parse_mounts(mounts.stdout) if mounts.ok else [],
            usage=parse_df(usage.stdout) if usage.ok else [],
            block=(await t.run(s.HAS_BLOCK)).exit_status == 0,
        )
