# System

The System screen shows a router's own state and changes its system settings: the overview, live load and
traffic, the logs and processes, network diagnostics, host name and time, services and the startup script,
scheduled tasks, a backup and a reboot. Open it from the router's sections. Each part is a tab; the tab you
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

## Backup

**Create backup** saves the router's configuration archive (`sysupgrade -b`, the same archive LuCI's backup
gives) in the app's data folder, readable by your Windows user only, and lists it with its size and time;
**Download** saves a copy where you choose. The archive holds the router's password hash, its SSH host keys,
this app's key and the Wi-Fi keys: keep it like a password. The audit log names the file, never its content.
Restoring a backup comes with a later version.

## Reboot

The preview shows the exact command: the router arms a timer that reboots it 2 seconds later, so the command
returns (and is audited) before the router goes down. The screen then follows the reboot: armed, waiting, and
back once the router answers with an uptime younger than the time since the reboot was armed (the only proof
that it really restarted). A router not back after 5 minutes is reported "not back": check its power and LEDs,
then Reconnect. LTE and Wi-Fi come back with the router; the LuCI bridge and the terminal reconnect by
themselves.
