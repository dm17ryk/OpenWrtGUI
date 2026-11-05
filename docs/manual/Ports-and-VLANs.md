# Ports, VLANs, mirroring

The router's switch: its sockets, the VLANs they carry, and port mirroring, as LuCI's Network › Switch page does
them. This works on routers whose switch `swconfig` manages, such as the bench's D-Link DWR-921 (`switch0`, five
sockets). For any other router, the screen says its switch is not managed and shows no ports.

![Ports, VLANs, mirroring](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/ports.png)

## Front panel

The sockets in the order printed on the case, each with its name, its switch port number, a link light with the
speed, and an on/off switch. Turning a socket off shows the one `swconfig` command first; it lasts until the next
reboot or network reload, when the socket comes back on. **Enable all ports** turns every socket back on at once.

## This app's port

The socket this app's SSH comes in on cannot be turned off, so it shows **carries this app's SSH** instead of a
switch. The app finds it in the switch's address table (the entry for this PC's MAC address), or, if the switch
has no such table, it is the only socket with a link in the VLAN that carries the app's interface. When several
sockets have a link there, each shows **may carry this app's SSH**, and all of them stay on.

## VLANs

One row per VLAN and one column per socket, with the router's CPU port last. Click a cell to cycle it: not a
member, then **U** (untagged), then **T** (tagged). A port can be untagged in one VLAN only, so the app refuses a
second one. A VLAN without the CPU port is out of the router's reach, and the preview warns about that. A VLAN
that carries an interface (such as `lan` on `eth0.1`) cannot be deleted until the interface moves to another
device. **+ Add VLAN** adds a row with the next free number. VLAN changes apply with the 60 s
[rollback](Network-and-DHCP#rollback).

## Switch port mirror

Choose a **Monitor port** and tick the sources: **RX** copies what a socket receives, **TX** what it sends. The
monitor port cannot also be a source. The PC on the monitor port sees copies of the sources' frames: capture with
its network card in promiscuous mode (Wireshark's default). The mirror is saved in the network settings and applies
with the rollback; choose **off** to stop it.

## Wi-Fi mirror

Whether the router has the `wifi-mirror` service, and whether it runs: **present · running**, **stopped**, or
**not on this router**. Stop and restart come with image import (v0.5).
