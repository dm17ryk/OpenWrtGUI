# FAQ

**Does the app store my router's root password?**
No. You type it once in the Add-router wizard; the app uses it to install its own SSH key and discards
it. From then on it logs in with that key.

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

**Can I change Wi-Fi channels or the firewall with it?**
Not in v0.1, which only reads (plus installing the key). Wi-Fi comes in v0.2, network in v0.3, and the
firewall in v0.4; see the [roadmap](https://github.com/dm17ryk/OpenWrtGUI/blob/master/ROADMAP.md).
Until then, the [terminal](Terminal-and-audit-log) gives you a shell.

**Will it interfere with a harness run?**
No. While [Bench Guard](Bench-Guard) sees a run, every router is read-only in the app. The dashboard's
reads are light (a few commands every 5 seconds per router).

**Is there a demo without routers?**
Yes, for developers: run it with `--simulator tests/fixtures/sim` from a source checkout (see
[CONTRIBUTING](https://github.com/dm17ryk/OpenWrtGUI/blob/master/CONTRIBUTING.md)). The screenshots in
this manual come from that simulator.
