# Tools

**Tools** holds the tool pages, one tab each. The chips under **Capabilities** on [Discovery](Discovery) open
them. A page opens even on a router that lacks what it needs; it then says what is missing. Both pages here only
read the router, so they keep working while [Bench Guard](Bench-Guard) shows a harness run.

## Port statistics

Each switch port's packets, bytes and errors, received and sent, from the switch's own counters: the MIB
counters that `swconfig dev switch0 show` prints, the same command the [Ports](Ports-and-VLANs) screen reads.
The tab reads them every 5 seconds while it is open and the window is in front, and stops when you leave it.

The numbers count from the moment the tab opened (**Since** shows the time); **Start over** starts counting again
from now. The router's own counters are never cleared: nothing is sent to the router but the read. **Rx rate** and
**Tx rate** come from the last two reads, in bits per second.

The counters are 32-bit, so a busy port wraps around after about 4 GB; a wrap is counted correctly. A counter that
goes down for any other reason, such as a router reboot, shows **reset** instead of a rate. Errors above zero are
marked. **All counters** under a port lists every counter the switch printed, under the switch's own names (on the
bench routers `TxGPC`, `TxGOC`, `RxEPC1` and so on), so a switch with other names still shows its numbers.

A router without a swconfig switch (a DSA router) says so: its ports have their own network devices, and their
counters come with the DSA backend.

## Connections

The router's connection tracking table: protocol, source and destination with ports, state, bytes, and the
conntrack helper that handles the connection (`sip` for a SIP call the router translates). The table is read every
5 seconds while the tab is open. It shows the first 500 entries, since the bench routers have only about 7 MB of
free memory; the summary says how many entries there are in all and how many the router allows.

Filter by protocol, by an address or a port (any part of it), or tick **SIP only** to keep the entries the SIP
helper handles. The counts by protocol above the table are for all the entries read. The System screen's
connection card links here with **All connections**.

## SIP ALG

The badge above the table says whether the router's SIP ALG is on: whether its firewall (fw4) hands SIP traffic to
the `sip` conntrack helper, which rewrites the addresses inside SIP messages. **SIP ALG on** names the zones and
the UDP port (5060 on the bench routers, zone lan); **SIP ALG off** means no zone uses the helper; **SIP ALG
unknown** means the router has no fw4 ruleset to read. The state is read from the firewall's ruleset when the tab
opens and on **Refresh**, not every 5 seconds. This page does not change it.
