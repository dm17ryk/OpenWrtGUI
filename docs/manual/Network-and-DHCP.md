# Network and DHCP

The router's addresses, its DHCP server, fixed addresses, who may join its Wi-Fi, DNS and routes: what LuCI's
Network › Interfaces, DHCP and DNS, and Routing pages do. Every change shows the exact commands first, and the
app reports it done only once the router proves it.

![Network and DHCP](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/network.png)

## Router addresses

Every interface the router has (lan, wan, lte, VLAN interfaces), with its protocol, address, gateway and DNS,
and whether it is up (with how long, for example **up · 2 h 14 min**). The one this app talks to the router
through is marked **this app's connection**.
Interfaces the router makes by itself while running (such as `lte_4`, made by `lte`) are listed read-only.

**Edit** opens the interface: choose its protocol (Static, DHCP client, No address, and whatever else the router
offers, such as LTE or PPP), and for Static its address, gateway, DNS servers and MTU. Write the address with its
prefix, for example `192.168.1.2/24`: a bare address means /32 on this firmware, so the app refuses it. For a
bridge (`br-lan`) you also choose its members. **Show all options** lists every other option the router's own
protocol list knows, so a protocol a newer image brings is editable at once.

**+ Interface** adds one (name, protocol, device). Put a new interface in a firewall zone afterwards: the
preview links the [Firewall](Firewall#zones) screen's Zones.

## Rollback

Every change to the router's network settings (addresses, bridges, routes, rules, VLANs, the switch mirror)
applies with a **60 s rollback**, the same way LuCI applies them. The router keeps a copy of its settings; after
the change the app connects to the router again, checks that the change is in effect, and only then confirms
(the router takes a few seconds to apply it). If it cannot reach the router within 40 s, the router puts its
previous settings back by itself 60 s after the change, and the app checks that they are back.

When you change the address of the interface this app talks through, the app reconnects at the **new**
address, but only if the router there has the same SSH host key; then it confirms and remembers the new
address. If this PC is not in the new subnet, the preview says so: the app can reach the router only through a
route, otherwise the change rolls back. The app refuses to delete that interface or to take its fixed address
away (DHCP client, No address), since it would have no address to reconnect to.

If a harness run starts while a change waits for its confirm, the app still confirms it and says so: a rollback
during the run would be a second change. While the app waits for the router, the card says "Applying with a 60 s rollback:
waiting for … to answer". [Firewall](Firewall) changes apply the same way.

## DHCP server

Per interface: on or off, the pool (first address and how many), the lease time (`12h`, `30m`, `infinite`),
options by code (3 router, 6 DNS servers, 15 domain, 42 NTP servers, or any code 1 to 254), and IPv6 (DHCPv6 and
router advertisements: server, relay, hybrid or disabled).

Before a server is turned on, the app checks every other router it knows: one that already serves DHCP on the
same subnet is named in a warning. On the bench, AP1 is the only DHCP server. A change is saved and dnsmasq (and
odhcpd for IPv6) reloaded; the app then reads the settings back and checks dnsmasq is running.

## Fixed addresses

A device by its MAC: a name, a fixed IP and lease time. **Gets an address** off lets the device join but hands it
no address. The app refuses a MAC or an IP that is already fixed for another device, and warns about an IP outside
every subnet of the router. Several changes go in one Apply.

## Active leases

The devices that have an address from this router now, with how long their lease still runs. **Make fixed** fills
in a fixed address for one of them.

## Wi-Fi access by MAC

Per SSID (all of them, or the ticked ones): **Everyone**, **Block listed**, or **Only listed**. **Only listed**
with an empty list would keep every device off, so the app refuses it.

A device can be blocked three ways:

- **Now · no Wi-Fi restart**: the router stops it at once, without restarting Wi-Fi. This lasts until the next
  Wi-Fi restart. The SSID must be on air.
- **For N s**: the router disconnects the device and refuses it for 10 to 3600 seconds.
- **Saved**: the device goes on the SSID's saved list (an SSID set to Everyone switches to Block listed). Wi-Fi
  restarts to take it, as on the Wi-Fi screen.

## DNS

The router's DNS forwarders (`8.8.8.8`, `8.8.8.8#53`, or `/bench/192.168.1.1` for one domain), the local domain,
rebind protection, per-domain overrides (a host name that answers with an address you choose), switches such as
logging queries, the cache size, and any other dnsmasq option the router has set.

## Static routes and rules

IPv4 and IPv6 routes (interface, target `address/prefix`, gateway, metric, table) and policy rules (from, to,
in, out, table, priority). They apply with the rollback, since a route can cut this app's own path as surely as
an address can. After the change the app looks for each route in the router's live routing table, which the
card also shows.
