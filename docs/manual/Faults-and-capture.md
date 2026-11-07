# Faults and capture

Breaks one device's connection on purpose, the way a panel under test meets a cable pulled, a dead link or a bad
network, and captures traffic on the router. Each fault shows the exact commands first, runs only after **Arm**,
and is reported as armed only when the router shows it in place. Every fault the app arms leaves a record in
`/tmp/owg` on the router, so the screen (and the router's card on the Dashboard, "N faults armed") still lists it
after the app or this PC restarts. A reboot of the router ends every fault.

While [Bench Guard](Bench-Guard) shows a run, nothing can be armed; clearing still works.

## Target

The device the fault hits: a Wi-Fi station, a host from the router's DHCP leases or address table, or a
[known device](Settings#known-devices). **other IP / MAC…** takes any address; the app fills in the other half
from what the router knows. **Remember as** keeps a MAC under a name. A panel's Ethernet and Wi-Fi MAC addresses
are unrelated, so the app never matches by vendor prefix. This PC and the router itself are refused as targets.

## Link down

Turns the switch port the target is plugged into off: real carrier loss, so its network interface goes down.
Ethernet only: a switch port cannot disconnect a Wi-Fi station (use Deauth or AP down). The port comes from the
switch's address table; when the switch does not list the target, pick the port. The port that carries this
app's SSH cannot be turned off.

## Isolate

Link and carrier stay up; every frame to and from the target's MAC is dropped, ARP included. It runs as the app's
own chains in the nftables table `benchfault`, bound to the port or Wi-Fi interface that leads to the target.

## Block flows

Drops some of the target's traffic: **rtp_in** / **rtp_out** (the RTP ports of its calls, read from the router's
connection tracking, so start the call first), **sip_in** (SIP to it, from or to port 5060 or 5061),
**all_in**, **all_out** or **blackout** (both ways). **Loss** below 100 % drops that share of the packets at
random. The rules sit ahead of fw4's `ct state established accept`, so they also hit a call already in progress.

## Impair (netem)

Delays, jitters, loses, reorders or duplicates the target's packets with `tc netem`, only for the target: other
hosts on the same port are not touched. **Direction**: to the target, from it (needs the router's `ifb` module),
or both. The **normal**, **pareto** and **paretonormal** distributions need their tables in `/usr/lib/tc`; on a
router without them those choices are greyed. A port that already has someone else's traffic-control setup is
refused, never replaced.

## Wi-Fi faults

**Deauth** kicks one station, which then re-joins: the Wi-Fi equivalent of pulling a cable. **Block** keeps it out
for the given seconds (10 to 3600; hostapd ends it by itself, and **Clear** ends it early). **AP down** stops the
access point the station is on, which drops every station on it. These need a Wi-Fi station as the target and an
SSID on air.

## Duration

**Until cleared** keeps the fault until you clear it. **Hold, then clear** gives it a time (5 s to 24 h): a timer
on the router itself clears it, so it ends on time even if this PC or the app goes away. The armed list shows the
time left.

## Clear everything

Clears every fault this app armed on the router: its chains, the `benchfault` table, netem, switch ports and
access points it took down, Wi-Fi blocks, and its records. **Clear** on a row clears one fault. A fault's record
goes only once the router shows the fault gone; a fault still there stays listed, with what is left, so it can be
cleared again. The last fault to go also removes the `benchfault` table. Clearing works during a run too,
because a fault left in place disturbs the run more; it then says "Cleared although Bench Guard is live". It never
touches anything the app did not arm.

## Capture

Captures on a router interface: `br-lan` (wired and Wi-Fi), a Wi-Fi interface, `mon0` (raw 802.11, created on the
radio for the capture and removed afterwards; not during a run) or the LTE interface. **Filter** takes a tcpdump
filter such as `host 192.168.1.30 and udp`; **Duration** is 1 to 3600 s. **Save .pcap** writes the file to
`Documents\OpenWrtGUI\captures`; **Live in Wireshark** (shown when Wireshark is installed) opens it live. The app's
own SSH connection is never captured. Captures keep working during a run.
