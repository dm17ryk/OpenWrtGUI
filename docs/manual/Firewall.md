# Firewall

The router's firewall as fw4 (firewall4, nftables) runs it: which traffic each zone lets through, the rules that
make exceptions, port forwards, NAT rules, IP sets, custom rule files, and every other nftables table on the
router, as LuCI's Network › Firewall and Status › Firewall pages show them. A router that does not run fw4 says
so, with a link to LuCI's own firewall pages.

Every change shows the exact commands first and applies with the 60 s [rollback](Network-and-DHCP#rollback): a
firewall rule on any zone can match this PC, so if the app cannot reach the router again and confirm, the router
restores its previous firewall by itself. While [Bench Guard](Bench-Guard) shows a run, changes are refused; the
rules, the counters and the raw ruleset keep working.

## Filtering model

One row per zone and one column per direction: **To this router** (input), **Through the router** (forward) and
**From this router** (output). Each cell is **Allow all** (everything passes and your rules block) or **Block all**
(nothing passes and your rules allow). **Blocked traffic is** chooses how Block all refuses: **Rejected** tells
the sender, **Dropped** stays silent.

Switching a cell keeps every rule. **Your rules in this model** shows what each rule does once the change
applies, with its live packet count. A rule that only repeats what its zone already does is flagged **no effect**:
it stays in the config, so switching back restores it; delete it on Traffic rules if you no longer need it. The
zone that carries this app's connection shows **carries this app's SSH**.

## Pinned rules

When the zone that carries this app's SSH blocks traffic to the router, the app keeps two rules open there so it
cannot lock itself out: **Allow SSH from this PC** (this PC's address, the router's SSH port) and, when the router
serves DHCP on that zone, **Allow DHCP and DNS** (so the panels under test still get addresses and names). They
are added with the change and named `owg_pin_ssh` and `owg_pin_dhcpdns` in the firewall config.

**Remove…** explains what you lose first. Without the SSH rule the app loses the router as soon as the change
applies, and the rollback then restores the old firewall by itself. **Put back** keeps the rule. Pins are changed
only here: on Traffic rules they cannot be edited, turned off or deleted. Switching the zone back to Allow all
keeps them; they then show as no effect.

## Zones

Each zone with its networks, its input, forward and output policies, **Masquerade** (NAT for traffic leaving
through it), **MSS clamp** (fixes the TCP segment size on links with a smaller MTU) and the zones it forwards to.
**Edit** opens the zone; **+ Zone** adds one. Networks are the router's interfaces. Other options lists the
zone's remaining settings by name. The zone that carries this app's connection cannot be deleted, and its
interface stays in it. A zone that rules, forwardings, port forwards or NAT rules still use must lose them first.

## Traffic rules

fw4's rules in the order it applies them, each with where it applies (zone and direction), what it matches, its
action, its live packet counter and its effect in the model. **+ Rule** adds one; a rule can be edited, turned off
or deleted. Names are 1 to 64 letters, digits, spaces, `.`, `-` or `_`, and must be unique.

## Port forwards

Traffic arriving on a zone's port that the router sends on to a device behind it (fw4 `redirect` sections): the
outside port or range, the device's address and its port.

## NAT rules

Source NAT for traffic leaving a zone (fw4 `nat` sections): **SNAT** rewrites the sender to a given address
(**Rewrite to**, and **Rewrite port**), **MASQUERADE** to the outgoing interface's address, **ACCEPT** exempts
traffic from NAT. Each rule names its **Zone** and can narrow by source, destination, port and protocol.
Masquerading a whole zone is set on the zone itself. **+ NAT rule** adds one; changes apply with the rollback.

## IP sets

Named lists of addresses, networks, ports or MAC addresses that rules can match in one go, kept by fw4 (`ipset`
sections), for example all panel MACs. Each set has a **Name**, a **Family** (ipv4 or ipv6), what it **Match**es
(such as `src_ip` or `src_mac`) and its **Entries**, one per line. **+ IP set** adds one; rules in the firewall
config then use it by name. Changes apply with the rollback.

## Custom rules

Files in `/etc/nftables.d` that fw4 loads into its own table. A file that came with the router's image is marked
**from the image**. The app checks the new rules with fw4 before it reloads; if fw4 refuses them, the old file
comes back at once and the error shows.

## Other nftables tables

Every nftables table and hook on the router, with its owner: **fw4**, **this app** (the faults table `benchfault`
and tables named `owg_…`), a known harness from [Settings](Settings) (such as `BENCHSIPGUARD` for dima_night or
`voipdscp` for the VoIP chain) or **unknown**. Tables owned by someone else are locked: **Unlock** says who relies
on them first. An unlocked table's rules can be edited, the table deleted, or a new table added. Each change is
runtime-only or kept as an fw4 include, and is applied atomically with a 60 s restore timer on the router.
`benchfault` is changed only on the [Faults](Faults-and-capture) screen (**Open faults**), so the faults listed
there stay true.

## Raw ruleset

The router's whole nftables ruleset (`nft -a list ruleset`), read-only and refreshed every 5 s: fw4's own table,
every other table, and the handle number of each rule. **Copy** puts the text on the clipboard, for a search in an
editor or a bug report. Nothing here changes the router: edit fw4's rules on the other tabs, and see who owns
another tool's table on Other nftables tables.

## Legacy iptables

LuCI's iptables view, on routers that have `/usr/sbin/iptables`: an older firewall (fw3), whose screen here
shows only this tab, or fw4 with iptables installed beside nftables. Both of LuCI's pages for it open this tab.

The rules of each table LuCI shows (filter, nat, mangle, raw, and the same for IPv6 when ip6tables is there),
chain by chain, with the policy or the references, each rule's counters, target, protocol, interfaces,
addresses and options, and its comment. **Hide empty chains** keeps only chains with rules.

- **Reset counters** clears the filter table's counters (iptables and ip6tables), as LuCI's button does; nat,
  mangle and raw keep theirs. The proof is given for iptables and, when the router has it, ip6tables: some
  counter that had counted is lower afterwards, which only a reset makes happen.
- **Restart firewall** restarts the firewall service; the proof is the filter table's rules back.

A line of a listing the app cannot read is not shown; the tab says how many there are.

On the bench image (fw4, no iptables) the tab says so: fw4's rules are under Raw ruleset.
