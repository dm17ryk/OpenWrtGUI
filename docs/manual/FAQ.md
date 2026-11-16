# FAQ

**Does the app store my router's root password?**
No. If you type it in the Add-router wizard, the app uses it once to install its own SSH key and discards
it. From then on it logs in with that key.

**My routers already accept my PC's SSH key. Do I need the app key?**
No. The wizard tries this PC's own keys (`id_ed25519`, `id_ecdsa`, `id_rsa` in `%HOME%\.ssh` and your
profile's `.ssh`) before asking for anything. If the router trusts one, the app keeps using that key and
changes nothing on the router.

**Why does the wizard try `root` / `root`?**
It is a common factory default on bench routers. The wizard tries it after the keys, and only if
nothing else worked; the password is never stored. If it works, the wizard tells you so: think about
changing it.

**What exactly does installing the app key change on the router?**
One line is appended to `/etc/dropbear/authorized_keys`, only if it is not there already. Nothing
restarts, and password login keeps working. The wizard shows the exact command before it runs.

**Can I remove the app's access later?**
Delete the line ending in `openwrtgui@<your PC>` from `/etc/dropbear/authorized_keys` on the router.

**Can I use it from another PC or my phone?**
No. The app only listens on `127.0.0.1` of the PC it runs on, by design.

**Does it work with routers other than the D-Link DWR-921?**
Any standard OpenWrt router you can reach over SSH. It reads the router's self-description the way LuCI
does. If something looks wrong, open a
[New router support](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose) issue with the outputs
it asks for.

**What can it change?**
Wi-Fi (modes, channels, power, security, step-throughs), the network (addresses with a 60 s rollback, DHCP,
DNS, routes), ports and VLANs, the firewall and faults, the LTE modem, and the System screen (host name, time,
services, scheduled tasks, access, LEDs, backups, restore). Every change shows its exact commands first and
is checked on the router afterwards. A LuCI page the app has no screen for yet opens inside the app.

**What does the app leave on a router?**
The line in `/etc/dropbear/authorized_keys` that lets it log in, plus a few things only when you use the feature
(pinned firewall rules, an armed fault's record). The full list is in [Files and data](Files-and-data#on-a-router).

**Will it interfere with a harness run?**
No. While [Bench Guard](Bench-Guard) sees a run, every router is read-only in the app. The dashboard's
reads are light (a few commands every 5 seconds per router).

**What does the 60 s rollback do if a change cuts the app off?**
The router keeps a copy of its settings and puts it back by itself 60 s after the change, unless the app reached
the router again and confirmed. So a wrong address or firewall rule cannot lock you out for long. See
[How changes work](How-changes-work#apply-with-rollback).

**Why does a screen say the router is busy?**
A router runs one job at a time (a reboot, a restore, a reset, a flash, an LTE action), and a second one is
refused until the first ends. Nothing was sent for the refused one. See
[Troubleshooting](Troubleshooting#the-router-is-busy).

**Why does the LTE screen say "no address yet"?**
The modem is registered, but the carrier has not given the router an address yet; a wrong APN is the usual
cause when it stays. See [Troubleshooting](Troubleshooting#the-lte-modem-has-no-address).

**When would I still use a LuCI page?**
Every LuCI page on the bench image has a screen here. A LuCI page opens inside the app for what a newer image adds.
Changes saved in LuCI skip this app's preview and use LuCI's own rollback. See [LuCI pages](LuCI-pages).

**Do I need Wireshark?**
Only to watch a capture live. A capture to a file needs nothing extra: it goes to `Documents\OpenWrtGUI\captures`
and opens in Wireshark later. See [Faults and capture](Faults-and-capture#capture).

**Is there a demo without routers?**
Yes, for developers: run it with `--simulator tests/fixtures/sim` from a source checkout (see
[CONTRIBUTING](https://github.com/dm17ryk/OpenWrtGUI/blob/master/CONTRIBUTING.md)). Unless you pass
`--data-dir`, the simulator keeps its data in a separate `<data folder>-simulator` folder, so its fake
routers and host keys never mix with your real ones. The screenshots in this manual come from it.
