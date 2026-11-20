# Tools

**Tools** holds the tool pages, one tab each. The chips under **Capabilities** on [Discovery](Discovery) open
them. A page opens even on a router that lacks what it needs; it then says what is missing. **Port statistics** and
**Connections** only read the router, so they keep working while [Bench Guard](Bench-Guard) shows a harness run.
**Throughput** and the **Traffic generator** send traffic, so they are refused during a run, and one that is
running stops within a second when a run starts.

## Port statistics

![Port statistics: each switch port's packets, bytes, errors and rates](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/tools-port-stats.png)

Each switch port's packets, bytes and errors, received and sent, from the switch's own counters: the MIB
counters that `swconfig dev switch0 show` prints, the same command the [Ports](Ports-and-VLANs) screen reads.
The tab reads them every 5 seconds while it is open and the window is in front, and stops when you leave it.

The numbers count from the moment the tab opened (**Since** shows the time); **Start over** starts counting again
from now. The router's own counters are never cleared: nothing is sent to the router but the read. **Rx rate** and
**Tx rate** come from the last two reads, in bits per second.

The switch's counters wrap around: on the bench routers the byte counters after about 4 GB, the packet and error
counters after 65,536. The page reads them often enough to see each wrap, and adds up every step, so the counts
since the start stay right however many times a counter wraps. A counter that goes down for any other reason, or
jumps faster than the port's link could carry, was reset (a router reboot, for example): the rate shows **reset**
for that read, and the counts go on from the counter's new value. Errors above zero are marked. **All counters** under a port lists every counter the switch printed, under the switch's own names (on the
bench routers `TxGPC`, `TxGOC`, `RxEPC1` and so on), so a switch with other names still shows its numbers.

A router without a swconfig switch (a DSA router) says so: its ports have their own network devices, and their
counters come with the DSA backend.

## Connections

![Connections: the SIP ALG badge, the filters and the connection table with its helpers](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/tools-connections.png)

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

## Throughput

Measures how fast data goes between the router and another machine, with `iperf3` on the router. The results
come in each second while the test runs, and **Stop** ends it on the router. iperf3 must be on the router (the
**Throughput** chip on Discovery says so). Choose what the router does:

- **connects to a host**: the router runs the iperf3 client against a host you name (an IPv4 address or a name),
  over TCP or UDP, for 1 to 60 seconds. **Router sends** measures what the router can send; **Router receives**
  asks the other side to send (`-R`). UDP sends at the **UDP rate** you set, 1 to 1000 Mb/s. The other machine must
  run `iperf3 -s`.
- **waits for a client**: the router runs one iperf3 server test (`iperf3 -s -1`) and waits up to 5 minutes for
  your PC's iperf3 to connect. The preview shows the command to run on your PC.

The preview shows the exact command. **Start** runs it on its own connection to the router, and the table fills in
each second: the rate, and the retransmits (TCP) or the jitter and loss (UDP). The totals and the router's CPU use
follow at the end. **Stop** ends it on the router. iperf3 runs on the router's CPU: on a small router the result is
often the CPU's limit, not the link's. Only one Throughput or Traffic generator listen runs on a router at a time.

## Traffic generator

Sends or takes simple traffic with `socat` on the router, to check that a port is open, that a device answers, or
what a device sends to the router. **Listen** waits for peers; **Send** sends zeros or a line of text. socat must be
on the router (the **Traffic generator** chip on Discovery says so).

**Listen** waits on a TCP or UDP port for 10 to 300 seconds. Each peer that connects or sends is listed with its
address and port, the bytes it sent, and its first 64 bytes in hex. The router shows the bytes in blocks of up to
4 KB, and in full when the peer closes; a UDP sender counts as gone 2 seconds after its last datagram. A listen
stops by itself at 50 MB.

**Send** sends a number of zero bytes (up to 10,000,000), or one line of printable text, to a host and port over
TCP or UDP, for at most 30 seconds. The result says what was sent, or socat's own error (for example **Connection
refused** when nothing listens on that port).
