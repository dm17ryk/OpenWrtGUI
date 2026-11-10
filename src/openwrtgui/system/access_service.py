"""System › Access, LEDs and Mount points (v0.6c plan): reads first; each write comes with its task. Kept
apart from SystemService so that file stays small. Every read is its own exec; a part that fails is named."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

import asyncssh
from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.audit import AuditLog, mask
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.net.apply import (
    NOTHING,
    ROLLBACK_S,
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    Snapshot,
    net_plan,
    rollback_warning,
    saved_check,
)
from openwrtgui.net.commands import INTERFACE_DUMP
from openwrtgui.net.parse import parse_interface_dump
from openwrtgui.probe.commands import ROOT_PASSWORD_STATE
from openwrtgui.store.keys import AppKey
from openwrtgui.store.routers import RouterRecord, RouterStore, router_key_paths
from openwrtgui.store.settings import KnownKey, SettingsStore
from openwrtgui.system import commands as s
from openwrtgui.system.access import (
    HttpChange,
    HttpState,
    PasswordPolicy,
    RepoKey,
    SshChange,
    SshInstance,
    check_password,
    dropbear_instances,
    http_ops,
    parse_dropbear,
    parse_listeners,
    parse_policy,
    parse_uhttpd,
    policy_ops,
    ssh_ops,
)
from openwrtgui.system.commands import OWNER
from openwrtgui.system.leds import LedChange, LedInfo, LedRow, led_ops, parse_led_sections, parse_leds
from openwrtgui.system.mounts import Mount, Usage, parse_df, parse_mounts
from openwrtgui.system.sshkeys import (
    FINGERPRINT,
    KeyLabel,
    KeysChange,
    check_key_line,
    label,
    parse_authorized_keys,
    render_authorized_keys,
)
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)

SCREEN = "System"
LISTEN_WAIT_S = 10.0  # procd restarts dropbear a few seconds after rpcd's apply


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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sleep = sleep
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

    async def _interfaces(self, t: Transport, host: str, missing: list[str]) -> tuple[str | None, set[str]]:
        """The interface holding the address the app uses, and every interface's name."""
        dump = await t.run(INTERFACE_DUMP)
        if not dump.ok:
            missing.append("interfaces")
            return None, set()
        try:
            live = parse_interface_dump(json.loads(dump.stdout))
        except ValueError:
            missing.append("interfaces")
            return None, set()
        mine = next((i.name for i in live if any(a.ip == host for a in i.ipv4)), None)
        return mine, {i.name for i in live}

    async def _app_interface(self, t: Transport, host: str, missing: list[str]) -> str | None:
        return (await self._interfaces(t, host, missing))[0]

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

    # ---------------------------------------------------------------- SSH keys (D5)
    def set_key_owner(self, fingerprint: str, owner: str | None) -> None:
        """Name a harness's key (Settings.known_keys); None forgets it. Nothing is sent to a router."""
        if not FINGERPRINT.fullmatch(fingerprint):
            raise ValueError(f"{fingerprint!r} is not a SHA256 key fingerprint")
        if owner is not None and not OWNER.fullmatch(owner):
            raise ValueError("An owner is 1-40 letters, digits, spaces, dots, dashes or underscores")
        settings = self._settings.load()
        keys = [k for k in settings.known_keys if k.fingerprint != fingerprint]
        if owner is not None:
            keys.append(KnownKey(fingerprint=fingerprint, owner=owner))
        self._settings.save(settings.model_copy(update={"known_keys": keys}))

    async def _keys_plan(
        self, rec: RouterRecord, t: Transport, change: KeysChange
    ) -> tuple[NetPlan, str, set[str]]:
        result = await t.run(s.KEYS_READ)
        if not result.ok and "No such file" not in result.stderr:
            raise ValueError(f"{s.AUTHORIZED_KEYS} does not read: {result.stderr.strip()}")
        rows = self.key_rows(rec, result.stdout if result.ok else "")
        by_print = {r.fingerprint: r for r in rows if r.fingerprint}
        warnings: list[str] = []
        for fingerprint in change.remove:
            row = by_print.get(fingerprint)
            if row is None:
                raise ValueError(f"No key {fingerprint} on {rec.name}")
            if row.label == "app":
                raise ValueError(f"The app logs in to {rec.name} with this key: it cannot be removed here")
            if row.label == "harness":
                warnings.append(f"{row.owner} uses this key: it can no longer log in to {rec.name}")
        kept = [r.text for r in rows if r.fingerprint is None or r.fingerprint not in change.remove]
        present = {r.fingerprint for r in rows if r.fingerprint and r.fingerprint not in change.remove}
        added: set[str] = set()
        for line in change.add:
            key = check_key_line(line)
            assert key.fingerprint is not None
            if key.fingerprint in present or key.fingerprint in added:
                raise ValueError(f"This key is on {rec.name} already ({key.fingerprint})")
            added.add(key.fingerprint)
            kept.append(key.text)
        text = render_authorized_keys(kept)
        if text == (result.stdout if result.ok else ""):
            raise ValueError(NOTHING)
        command = s.write_file("/etc/dropbear/authorized_keys", text)
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[command],
            warnings=warnings,
        )
        return plan, text, added

    async def plan_keys(self, router_id: str, change: KeysChange) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._keys_plan(rec, t, change))[0]

    async def _still_logs_in(self, rec: RouterRecord) -> NetCheck:
        """A new connection with the app's key runs a command: the write did not lock the app out."""
        try:
            t = await self._pool.fresh(rec)
        except TransportError as exc:
            return NetCheck("the app still logs in", False, f"a new login failed: {exc}")
        try:
            ok = (await t.run("true")).ok
        finally:
            await t.close()
        return NetCheck(
            "the app still logs in", ok, "a new login with the app's key works" if ok else "refused"
        )

    async def apply_keys(self, router_id: str, change: KeysChange, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, text, added = await self._keys_plan(rec, t, change)

            async def verify(t2: Transport) -> list[NetCheck]:
                read = await t2.run(s.KEYS_READ)
                saved = read.ok and read.stdout == text
                present = {k.fingerprint for k in parse_authorized_keys(read.stdout if read.ok else "")}
                missing = added - present
                return [
                    NetCheck(
                        "saved",
                        saved,
                        "the router has the new file" if saved else "the file read back differs",
                    ),
                    NetCheck(
                        "added",
                        not missing,
                        "every new key is there" if not missing else "a new key is missing",
                    ),
                    await self._still_logs_in(rec),
                ]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- LEDs (D9)
    async def _leds_plan(
        self, rec: RouterRecord, t: Transport, change: LedChange
    ) -> tuple[NetPlan, dict[str, str]]:
        leds = await t.run(s.LEDS)
        if not leds.ok:
            raise ValueError(f"{rec.name} does not list its LEDs (LuCI's rpcd plugin is missing)")
        text = await self._stdout(t, s.UCI_SYSTEM)
        devices = (await self._stdout(t, s.NET_DEVICES)).split()
        ops = led_ops(
            parse_led_sections(text), change, parse_leds(leds.stdout), devices, router_name=rec.name
        )
        current = parse_uci_show(text)
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="system",
            ops=ops,
            current=current,
            reloads=[s.init("led", "restart")],
        )
        return plan, current

    async def plan_leds(self, router_id: str, change: LedChange) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._leds_plan(rec, t, change))[0]

    async def _active(self, t: Transport, rows: list[LedRow]) -> list[NetCheck]:
        """`LED <name>`: each LED's active trigger is its row's (/etc/init.d/led applied them)."""
        checks: list[NetCheck] = []
        for _ in range(int(LISTEN_WAIT_S)):
            active = {i.sysfs: i.active for i in parse_leds(await self._stdout(t, s.LEDS) or "{}")}
            checks = [
                NetCheck(f"LED {r.sysfs}", active.get(r.sysfs) == r.trigger, f"trigger {active.get(r.sysfs)}")
                for r in rows
            ]
            if all(c.ok for c in checks):
                break
            await self._sleep(1.0)
        return checks

    async def apply_leds(self, router_id: str, change: LedChange, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, current = await self._leds_plan(rec, t, change)

            async def verify(t2: Transport) -> list[NetCheck]:
                saved = await saved_check(t2, s.UCI_SYSTEM, plan.ops, current)
                return [saved, *await self._active(t2, change.rows)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- HTTP(S) access (D6)
    async def _http_plan(
        self, rec: RouterRecord, t: Transport, change: HttpChange
    ) -> tuple[NetPlan, dict[str, str], HttpState]:
        text = await self._stdout(t, s.UCI_UHTTPD)
        current, http = parse_uci_show(text), parse_uhttpd(text)
        listening = parse_listeners(await self._stdout(t, s.LISTENERS))
        served = bool(https_ports(http) & {port for _, port in listening})
        ops = http_ops(http, change, https_served=served, router_name=rec.name)
        warnings = [f"uhttpd restarts: LuCI on {rec.name} is away for a second, in browsers and in this app."]
        if change.luci_on_network is False:
            warnings.append(
                f"LuCI is no longer reachable from the network at {rec.name}'s addresses. LuCI pages in this "
                "app keep working: they come in through the app's SSH connection."
            )
        if change.redirect_https:
            warnings.append(
                f"Browsers that open http://{rec.host} are sent to https://{rec.host}. LuCI pages in this "
                "app follow."
            )
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="uhttpd",
            ops=ops,
            current=current,
            reloads=[s.init("uhttpd", "restart")],
            warnings=warnings,
        )
        return plan, current, parse_uhttpd(text)

    async def plan_http(self, router_id: str, change: HttpChange) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._http_plan(rec, t, change))[0]

    async def _web_check(self, t: Transport, on_network: bool | None) -> NetCheck:
        """`listening`: uhttpd listens where the switch says, loopback kept; polled while it restarts."""
        detail = "uhttpd does not listen on 127.0.0.1:80"
        for _ in range(int(LISTEN_WAIT_S)):
            web = {a for a, port in parse_listeners(await self._stdout(t, s.LISTENERS)) if port == 80}
            loop = "127.0.0.1" in web or "0.0.0.0" in web
            outside = bool(web - {"127.0.0.1", "::1"})
            if loop and (on_network is None or outside == on_network):
                where = "every address" if outside else "loopback only"
                return NetCheck("listening", True, f"uhttpd listens on {where}")
            detail = f"uhttpd listens on {', '.join(sorted(web)) or 'nothing'}"
            await self._sleep(1.0)
        return NetCheck("listening", False, detail)

    async def apply_http(self, router_id: str, change: HttpChange, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, current, _http = await self._http_plan(rec, t, change)

            async def verify(t2: Transport) -> list[NetCheck]:
                saved = await saved_check(t2, s.UCI_UHTTPD, plan.ops, current)
                return [saved, await self._web_check(t2, change.luci_on_network)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- SSH access (D4)
    async def _ssh_plan(
        self, rec: RouterRecord, t: Transport, change: SshChange
    ) -> tuple[NetPlan, dict[str, str], list[int]]:
        current = parse_uci_show(await self._stdout(t, s.UCI_DROPBEAR))
        existing = dropbear_instances(current)
        interface, names = await self._interfaces(t, rec.host, [])
        mine = app_instance(existing, rec.port, interface)
        ops, ports = ssh_ops(
            current,
            change,
            app_instance=mine.section if mine else None,
            app_interface=interface,
            interfaces=names,
            router_name=rec.name,
        )
        new_port = next(
            (i.port for i in change.instances if mine and i.section == mine.section and i.port != mine.port),
            None,
        )
        where = f"{rec.host} port {new_port}" if new_port else rec.host
        warnings = [rollback_warning(rec.name, where, "SSH settings")]
        if new_port:
            warnings.append(
                f"The app follows {rec.name} to port {new_port}. The firewall must let port {new_port} in "
                f"from {interface or 'the network this PC is on'}; without a confirm from port {new_port} "
                f"within {ROLLBACK_S} s the router puts its SSH settings back."
            )
        old = {i.section: i for i in existing}
        if any(
            i.section in old
            and (
                (old[i.section].password_auth and not i.password_auth)
                or (old[i.section].root_password_auth and not i.root_password_auth)
            )
            for i in change.instances
            if i.section is not None
        ):
            warnings.append(f"Scripts that log in to {rec.name} with a password lose SSH access.")
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="dropbear",
            ops=ops,
            current=current,
            rollback=True,
            target_port=new_port,
            warnings=warnings,
        )
        return plan, current, ports

    async def plan_ssh(self, router_id: str, change: SshChange) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._ssh_plan(rec, t, change))[0]

    async def _listening(self, t: Transport, ports: list[int]) -> NetCheck:
        """`listening`: dropbear answers on each enabled instance's port (procd reloads it after apply)."""
        missing = set(ports)
        for _ in range(int(LISTEN_WAIT_S)):
            listening = parse_listeners(await self._stdout(t, s.LISTENERS))
            missing = set(ports) - {port for _, port in listening}
            if not missing:
                return NetCheck("listening", True, "SSH listens on port " + ", ".join(map(str, ports)))
            await self._sleep(1.0)
        return NetCheck("listening", False, "nothing listens on port " + ", ".join(map(str, sorted(missing))))

    async def apply_ssh(self, router_id: str, change: SshChange, digest: str | None) -> NetApplyResult:
        """With the rpcd rollback: confirmed only from a new connection (on the new port when it moved)."""
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, current, ports = await self._ssh_plan(rec, t, change)

            async def verify(t2: Transport) -> list[NetCheck]:
                return [
                    await saved_check(t2, s.UCI_DROPBEAR, plan.ops, current),
                    await self._listening(t2, ports),
                ]

            return Planned(plan, verify, Snapshot(s.UCI_DROPBEAR, current))

        return await self._runner.run_planned(rec, make, digest)

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
