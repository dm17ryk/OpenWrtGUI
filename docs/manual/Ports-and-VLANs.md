# Ports, VLANs, mirroring

The router's switch: its sockets, the VLANs they carry, and port mirroring, as LuCI's Network › Switch page does
them. This works on routers whose switch `swconfig` manages, such as the bench's D-Link DWR-921 (`switch0`, five
sockets). On a DSA router, the screen edits the bridge's VLANs (see [VLANs on a DSA router](#vlans-on-a-dsa-router)).
For any other router, the screen says its switch is not managed and shows no ports.

![Ports, VLANs, mirroring](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/ports.png)

## Front panel

The sockets in the order printed on the case, each with its name, its switch port number, a link light with the
speed, and an on/off switch. Turning a socket off shows the one `swconfig` command first; it lasts until the next
reboot or network reload, when the socket comes back on. **Enable all ports** turns every socket back on at once.

## This app's port

The socket this app's SSH comes in on cannot be turned off, so it shows **carries this app's SSH** instead of a
switch. The app finds it in the switch's address table (the entry for this PC's MAC address), or, if the switch
has no such table, it is the only socket with a link in the VLAN that carries the app's interface. When several
sockets have a link there, each shows **may carry this app's SSH**, and all of them stay on. When the app cannot
tell at all how its connection reaches the switch, every socket with a link shows **may carry this app's SSH**
and stays on.

## VLANs

One row per VLAN and one column per socket, with the router's CPU port last. Click a cell to cycle it: not a
member, then **U** (untagged), then **T** (tagged). A port can be untagged in one VLAN only, so the app refuses a
second one. A VLAN without the CPU port is out of the router's reach, and the preview warns about that. A VLAN
that carries an interface (such as `lan` on `eth0.1`) cannot be deleted until the interface moves to another
device. **+ Add VLAN** adds a row with the next free number. VLAN changes apply with the 60 s
[rollback](Network-and-DHCP#rollback).

## VLANs on a DSA router

A router with a DSA switch has no swconfig switch: its ports (`lan1`, `lan2`, ...) are members of a bridge, and the
bridge's VLANs are `bridge-vlan` sections. On such a router the Ports screen shows **VLANs · switch** (the bridge's
name), which is LuCI's **Network › Switch/VLAN config**.

- Each row is a VLAN, and each column is one of the router's own ports, as board.json lists them. Click a cell to
  go from **—** (not a member) to **U** (untagged, the port's native VLAN) to **T** (tagged).
- Making a port untagged in one VLAN takes it out of the VLAN it was untagged in, as LuCI does. Its tagged
  memberships stay.
- **Local** means the router itself is in the VLAN. A new VLAN has it on.
- **+ Add VLAN** adds a VLAN with the lowest free number (1-4094). **Delete** removes a VLAN that no interface uses.
- An existing VLAN keeps its number. To renumber it, add the new VLAN and remove the old one.
- A control the router would refuse is greyed: rest the pointer on it to read why (for example a port that may
  carry this app's SSH, or a VLAN an interface still uses).
- Saving puts the entries in the order LuCI uses. LuCI lists the entries in its own order, and so does this
  editor after an Apply, so a VLAN may move in the list.
- An entry you did not change is written back as it was. LuCI rewrites, for example, `lan2:u*` as `lan2`.
- When LuCI's own page would refuse the configuration (a VLAN number out of range, an entry such as `lan1:t*`, a
  port untagged in two VLANs), the card lists the reasons and stays read only. Fix those in LuCI's device dialog or
  the terminal.
- Ports that Wi-Fi joins at run time are listed under the matrix and never edited.
- Port on/off, link state and mirroring on a DSA router are not here yet. LuCI's port and VLAN labels are left to
  LuCI.

**How the app keeps its own connection.** A VLAN change can cut the app off its router. Three things stand in the
way:

1. **Refused before the preview.**
   - The VLAN that carries the app's connection (the interface its SSH comes in on, on `switch.<vid>`) cannot be
     deleted or renumbered, and its **Local** stays on.
   - The ports with a link in that VLAN *may carry this app's SSH* (marked SSH in the header). At least one of them
     must keep its membership in that VLAN as it is.
   - When the interface sits on the bridge itself, or straight on one of its ports, the app cannot tell how a VLAN
     change reaches it, so the card is read only. So it is when the app cannot tell which interface its
     connection comes in on at all.
   - When that VLAN has no `bridge-vlan` section of its own (the bridge's default VLAN), the app does not add one
     here; set it up in LuCI.
2. **The 60 s rollback.**
   - Every change applies with a 60 s rollback, as LuCI's Save & Apply does.
   - The app reconnects over a new connection and checks netifd's own report of the bridge's VLANs. Only then does
     it confirm.
   - If the change cut the app off, nothing confirms it, and the router restores its previous network settings by
     itself 60 s after the change. This happens even if the app or the PC is gone.
3. **If the router does not come back.** The app checks at 65 s that the router answers again with its previous
   settings. If it does not:
   - Wait until **2 minutes** after the change, then **power-cycle** the router. After the rollback its flash holds
     the previous settings again.
   - Do not power-cycle sooner: during the 60 s window the flash holds the change.
   - If the router still does not answer, see
     [Troubleshooting](Troubleshooting#a-router-that-does-not-come-back-after-a-rollback).

The app cannot yet tell which port is your PC's, because standard images cannot list the bridge's address table.
So with two linked ports in its VLAN, it lets you move either one, and if you move your own, the rollback brings
the router back. There is no exact **own-port lock** in this version.

## Switch port mirror

Choose a **Monitor port** and tick the sources: **RX** copies what a socket receives, **TX** what it sends. The
monitor port cannot also be a source. The PC on the monitor port sees copies of the sources' frames: capture with
its network card in promiscuous mode (Wireshark's default). The mirror is saved in the network settings and applies
with the rollback; choose **off** to stop it.

## Wi-Fi mirror

Whether the router has the `wifi-mirror` service, and whether it runs: **present · running**, **stopped**, or
**not on this router**. Start, stop and restart it in [Discovery › Custom services](Discovery#custom-services).
