# Glossary

The words this manual and the app use, in alphabetical order. Each entry links to the page that explains it in
full.

**APN**: the access point name the LTE modem uses to reach the carrier's network. See [LTE modem](LTE-modem#settings).

**App key**: the SSH key pair the app creates on first start. With your OK, the app installs it on a router so it
can log in without a password. See [First router](First-router) and [Settings](Settings#app-ssh-key).

**AT command**: a text command sent to the LTE modem, such as `AT+CSQ` for the signal. The LTE screen's AT console
sends them. See [LTE modem](LTE-modem#at-console).

**Beacon**: the frame an access point sends about ten times a second to announce its network. The app reads real
beacons to prove a radio's settings. See [Wi-Fi](Wi-Fi#apply-and-proof-on-air).

**BSSID**: the MAC address a radio's network uses on air.

**Channel width**: how much spectrum a radio uses: 20 MHz (HT20) or 40 MHz (HT40) on 2.4 GHz, more on 5 and
6 GHz. See [Wi-Fi](Wi-Fi#channels).

**DSA**: Distributed Switch Architecture, the way newer OpenWrt routers present their switch. Each socket is its
own network device, and VLANs are set on a bridge. See [Ports, VLANs, mirroring](Ports-and-VLANs#vlans-on-a-dsa-router).

**fw4**: OpenWrt's firewall (firewall4). It builds nftables rules from `/etc/config/firewall`. See
[Firewall](Firewall).

**Host key**: the key a router's SSH server proves itself with. The app pins it when you add the router, and it
refuses to connect if the key changes. See [First router](First-router#2-check-the-router-is-the-one-you-mean) and
[Troubleshooting](Troubleshooting).

**IP set**: a named list of addresses, MAC addresses or ports that firewall rules match in one go. See
[Firewall](Firewall#ip-sets).

**LuCI**: OpenWrt's own web interface. See [LuCI pages](LuCI-pages).

**minstrel**: the Wi-Fi driver's rate control. It picks the data rate for each station.

**Monitor interface**: an extra interface on a radio that hears every frame on its channel. Frame analysis and
the channel scan add one for as long as they run, and then remove it. See [RF live](RF-live#frame-analysis).

**netem**: the Linux network emulator. It adds delay, loss, duplication or reordering to traffic. See
[Faults and capture](Faults-and-capture#impair-netem).

**netifd**: OpenWrt's network daemon. It brings interfaces up from `/etc/config/network`.

**nftables**: the Linux packet filter that fw4 uses. Other tools can keep their own tables beside fw4's. See
[Firewall](Firewall#other-nftables-tables).

**On air**: a radio that is up and transmitting. See [Dashboard](Dashboard#router-cards).

**Overlay**: the writable part of a router's flash, on top of the read-only image. It holds every file added or
changed since flashing. See [Discovery](Discovery#added-after-flashing).

**Parked**: a radio that is off but keeps the channel it would use. See [Dashboard](Dashboard#router-cards).

**Pinned**: saved and checked on every connection. The app pins each router's host key. The firewall's
[pinned rules](Firewall#pinned-rules) are the two rules the app keeps open for its own access.

**Profile**: what the app read from an imported sysupgrade image: board, revision and packages. See
[Settings](Settings#images).

**Proof on air**: the check after a Wi-Fi change that the radio really transmits as set: channel, width, TX
power, TX mask and beacon rate. See [How changes work](How-changes-work#proof-on-air).

**QMI**: the protocol OpenWrt uses to drive the LTE modem. See [LTE modem](LTE-modem).

**Read-only**: a router the app only reads, because a run is live. See [Bench Guard](Bench-Guard).

**Rollback**: the router's own copy of its settings. The router puts it back 60 s after a change unless the app
confirms the change. See [How changes work](How-changes-work#apply-with-rollback).

**Run**: a test harness working on the bench. Bench Guard finds it by its lock file, its process, or the SSID it
puts on air. While a run is live, every router is read-only. See [Bench Guard](Bench-Guard).

**Station**: a device connected to a radio, such as a phone or a panel.

**Step-through**: walking a radio through a list of modes, channels and TX powers. Each step is proven on air,
with a wait between steps. See [Wi-Fi](Wi-Fi#step-through).

**swconfig**: the older way OpenWrt presents a router's switch: one switch device with numbered ports, and VLANs
in `/etc/config/network`. See [Ports, VLANs, mirroring](Ports-and-VLANs#vlans).

**Sysupgrade image**: the firmware file (`.bin`) a router is flashed with. See
[Discovery](Discovery#flash-this-image).

**TX power**: the radio's transmit power, in dBm. See [Wi-Fi](Wi-Fi#tx-power).

**uci**: OpenWrt's configuration system: the files in `/etc/config`, and the `uci` command that changes them.

**Zone**: a group of the router's networks that share firewall policies, such as lan and wan. See
[Firewall](Firewall#zones).
