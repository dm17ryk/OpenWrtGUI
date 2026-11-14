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
The line in `/etc/dropbear/authorized_keys` that lets it log in. If you make the zone that carries the app's SSH
block traffic to the router, the change adds the [pinned rules](Firewall#pinned-rules) `owg_pin_ssh` and
`owg_pin_dhcpdns`, which stay until you remove them on the Firewall screen. An armed fault keeps its record under
`/tmp/owg` until it ends. **Clear everything** on the Faults screen removes faults left from a closed session.

**Will it interfere with a harness run?**
No. While [Bench Guard](Bench-Guard) sees a run, every router is read-only in the app. The dashboard's
reads are light (a few commands every 5 seconds per router).

**Is there a demo without routers?**
Yes, for developers: run it with `--simulator tests/fixtures/sim` from a source checkout (see
[CONTRIBUTING](https://github.com/dm17ryk/OpenWrtGUI/blob/master/CONTRIBUTING.md)). Unless you pass
`--data-dir`, the simulator keeps its data in a separate `<data folder>-simulator` folder, so its fake
routers and host keys never mix with your real ones. The screenshots in this manual come from it.
