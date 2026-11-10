# System

The System screen shows a router's own state and changes its system settings: the overview, live load and
traffic, the logs and processes, network diagnostics, host name and time, the router's password and its SSH
and web access, services and the startup script, scheduled tasks, the LEDs, the mount points, a backup with its
restore, a reboot and a reset to defaults. Open it from the router's sections. Each part is a tab; the tab you
are on is in the address (`?tab=logs`), so a link opens the same tab.

![System](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/system.png)

Reads work at any time, also while a harness run is live. Every change, a diagnostic and a reboot wait while
Bench Guard sees a run; the backup does not (it changes nothing on the router).

## Overview

The router's model and board, its firmware (release and revision), kernel, host name, local time, uptime, the
load average (1, 5 and 15 minutes), the memory still free, and the space left on the root and temporary file
systems. The app reads what LuCI's own status page reads (`ubus call system board` and `system info`). When a
part does not answer, the screen names it ("No answer from the router for: board") and shows the rest.

## Live load, bandwidth and connections

While the Status tab is open, the router is read every 3 seconds: the load average, the bytes per second of
each interface (pick one; received and sent are drawn apart), and the number of tracked connections. One read
covers all three, as LuCI's realtime graphs do. When the router does not answer, the reason shows above the
charts and the charts keep the last samples.

## Connections

**Show connections** lists the tracked connections: protocol, source and destination with their ports, the
state, and the bytes. The list is read once, on request, and holds at most 500 rows (the bench routers have
little free memory). A router without connection tracking says so.

## Logs

The system log (`logread`) and the kernel log (`dmesg`): pick which, and how many of the last lines (100, 500
or 2000). The filter keeps the lines whose text contains what you type; the level filter keeps a level and the
ones more severe. **Follow** reads the log again every 5 seconds while it is on.

## Processes

Every process `top` shows, with its PID, parent, user, state, memory and CPU share, sorted by CPU (click a
heading to sort by another column). The memory column is what the router prints: the bench routers print the
resident size (RSS). This view does not signal processes: use the [Terminal](Terminal-and-audit-log) for that.

## Diagnostics

**Ping**, **Traceroute** and **Nslookup** run on the router, to a host name or an address. The output shows
with the exact command that ran. A diagnostic stops after 25 seconds whatever the network does. It changes
nothing, but it sends traffic from a router under test, so it waits while a harness run is live; each one is
in the audit log.

## System and time

The host name (letters, digits and `-`, 1 to 63, not starting or ending with `-`), the time zone (from the
router's own list, plus UTC), the NTP client and server and the NTP servers to ask, the size of the log buffer
(16 to 1024 KiB), and a remote syslog server (an IPv4 address, a port and UDP or TCP; empty removes it). The
preview shows the exact `uci` commands and the init scripts that put them in effect (`system reload`,
`sysntpd restart`, `log restart`); none of them touches the network, so there is no rollback. **Apply**
proves the change: the saved config, the host name the router answers with, and the time zone it uses.

## Router password

The Access tab sets root's password, the one LuCI and password SSH logins use. Type it twice; it stays in the
page only, never in an address, the audit log or an answer, and both fields clear once the router answered.
The preview is `passwd root` whatever the password is: Apply sends the password on that command's input, never
on its command line. The proof is root's password hash: it must have changed. The app itself logs in with its
key and is not affected; a script that logs in with the old password stops working. When the router's
password policy is on, its rules are listed above the fields and a password that breaks one is refused before
anything is sent.

## Password policy

LuCI's Password Policy page (`rpcd.policy`): whether new passwords are checked, a minimum length, and whether
a digit, upper and lower case letters, or a special character are needed. A router without a policy has none
until Apply creates it. The policy checks the passwords set in this app and in LuCI; it does not change the
password the router has now.

## SSH access

dropbear's instances, one row each: on or off, the port, the interface it listens on (all interfaces or one),
password logins, root password logins, and gateway ports. **Add instance** adds a row; **Remove** drops one
at Apply. The instance the app connects through is marked "The app connects here": it cannot be turned off or
removed here, and it listens on the app's interface or on all of them. A change applies with a 60 s rollback:
the app must reach the router again on a new connection and confirm, or the router puts its SSH settings back
by itself. When the app's own port changes, the app follows it to the new port (the firewall must let it in).
The proof is the saved config and dropbear listening on every enabled port.

## SSH keys

`/etc/dropbear/authorized_keys`, one row per line: the key type, its comment, its SHA256 fingerprint and who
uses it. **App** is the key this app logs in with: it has no Remove. **Harness** is a key you named with
**Owner…** (the name is kept in the app's settings, nothing is sent to the router); **Other** is any other
key. **Add key** takes a pasted public key line; a private key, or a key the router has already, is refused.
The preview is the whole new file. The proof is the file read back, every new key in it, and a new login with
the app's key.

## HTTP(S) access

LuCI's HTTP(S) Access page: **Redirect HTTP to HTTPS**, and **LuCI on the network** (off: uhttpd listens on
the router's own address 127.0.0.1 only, so browsers on the network no longer reach LuCI; LuCI pages in this
app keep working, they come in through the app's SSH connection). The redirect stays off on a router that
serves no HTTPS, or LuCI would become unreachable. A router whose uhttpd keeps its own addresses (a custom
listen list) says so; switching LuCI on or off here replaces that list. uhttpd restarts at Apply; the proof is
the saved config and uhttpd listening where the switch says.

## Repository keys

The names of the keys the package manager trusts (`/etc/apk/keys`, or `/etc/opkg/keys` on older firmware).
They are shown, never changed here.

## Services

Every init script the router has, with whether it starts at boot (enabled) and whether it is running.
**Start**, **Stop**, **Restart**, **Enable** and **Disable** are proven by reading the services again within 10
seconds; a script that runs once at boot (no running process) is proven by its exit status. The services the
app itself goes through (dropbear, rpcd, uhttpd, network, firewall, log) offer only Restart, with the reason.
Restarting network, firewall, wpad or dnsmasq reloads the router's network: the preview says so, and on the
bench the txctl session must be told first.

## Startup script (rc.local)

`/etc/rc.local` runs once at the end of every boot. Edit it as text; the preview shows the exact write. Its
last line must be `exit 0` (the boot waits for it otherwise), and it is at most 8 KiB. After the write the file
is read back and must equal what was sent.

## Scheduled tasks

The router's crontab (`/etc/crontabs/root`), as rows: five time fields (minute, hour, day, month, weekday) and
a command, plus comments. A field cron cannot read is refused with its line number before anything is sent,
because such a task would silently never run. **Apply** writes the file, enables cron if it is disabled, and
restarts it; the proof is the file read back and cron running. A router without a crontab simply has no tasks:
cron idles until there is one.

## LEDs

LuCI's LED Configuration page: the LED actions (`led` sections of the system config) that
`/etc/init.d/led` applies. Each row has a name, the LED (from the router's own list, with what it does now),
the trigger (from that LED's triggers), and the options that trigger takes: on or off for none, the on and
off times for timer, inverted for heartbeat, the device and the modes (link, tx, rx…) for netdev, and the
port and speed masks for a switch trigger. **Add LED action** adds a row and **Remove** drops one at Apply.
The preview shows the exact `uci` lines and `/etc/init.d/led restart`; the proof is the saved config and each
LED's active trigger read back from the router. A router without LuCI's rpcd plugin cannot list its LEDs and
says so.

## Mount points

What is mounted where (device, type and mount options) and how full each file system is (size, used, free).
The view is read only. Editing `/etc/config/fstab` needs the block-mount package, which the bench images do
not have; the screen says so when it is missing.

## Backup

**Create backup** saves the router's configuration archive (`sysupgrade -b`, the same archive LuCI's backup
gives) in the app's data folder, readable by your Windows user only, and lists it with its size and time;
**Download** saves a copy where you choose. The archive holds the router's password hash, its SSH host keys,
this app's key and the Wi-Fi keys: keep it like a password. The audit log names the file, never its content.

## Import a backup

**Import backup…** brings a backup file from this PC into the router's list (`.tar.gz` or `.tgz`, 4 MiB at
most), for instance one LuCI saved. The app reads it on the PC first and refuses anything that is not a gzip
tar of plain files and folders under `etc/` (no links, devices, absolute paths or `..`); nothing goes to the
router. It is saved beside the router's own backups, readable by your Windows user only, and marked "imported
from this PC".

## Restore

Pick a backup from the list and **Check** it: the app reads the archive and lists its files, or says why it is
refused. A restore is refused before anything is sent when the backup is another router's (its SSH host key is
not this router's), when it would move the router off the address the app reaches it at, or when its
authorized keys lack the app's key (the app could not log in afterwards). The preview follows: the upload to
`/tmp/owg/restore.tar.gz` (one audited line; the bytes are never logged), `tar -tzf`,
`sysupgrade --restore-backup` and the reboot timer. **Restore and reboot** asks once more, then the screen
follows the reboot as the Reboot card does. Done means a fresh uptime and every restored file matching the
backup by its sha256. If a step fails before the reboot, the uploaded archive is removed from the router.

## Files kept in a backup

`/etc/sysupgrade.conf`, edited as text: one absolute path (a file or a folder) or `#` comment per line, 8 KiB
at most. A backup, and a flash that keeps settings, holds the config files changed since flashing plus these.
Beside it is what a backup holds now (`sysupgrade -l`). The preview is the whole new file; the proof is the
file read back. Removing the `/etc/owg/` line warns that a flash that keeps settings puts it back.

## Reboot

The preview shows the exact command: the router arms a timer that reboots it 2 seconds later, so the command
returns (and is audited) before the router goes down. The screen then follows the reboot: armed, waiting, and
back once the router answers with an uptime younger than the time since the reboot was armed (the only proof
that it really restarted). A router not back after 5 minutes is reported "not back": check its power and LEDs,
then Reconnect. LTE and Wi-Fi come back with the router; the LuCI bridge and the terminal reconnect by
themselves. A router runs one job at a time: a reboot, a restore or a reset.

## Reset to defaults

**Preview reset** shows the exact command: the router arms a timer that runs `firstboot -r -y` 2 seconds
later, which erases every setting. The router then comes back like a new one, at 192.168.1.1 with no password
and a new host key, which clashes with any other router at that address (AP1 on the bench). So **Start reset**
waits until you type the router's name and tick that it is alone on this PC's network. Done means the router
stopped answering at its address (within 120 seconds); its entry then shows "Reset to defaults: add it again"
under Needs attention, with **Add again**. Nothing more can be proven on the old address. On the bench this
runs in the simulator only, never on AP2.
