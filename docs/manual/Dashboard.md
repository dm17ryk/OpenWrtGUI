# Dashboard

The dashboard shows every router at once. It refreshes every 5 seconds over SSH and only reads; nothing
on this screen changes a router.

![Dashboard](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/dashboard.png)

## Headline

The title counts the bench: routers, radios on air, stations connected. For example
"3 routers · 1 radio on air · 1 station".

## Air map

One map per band that has a radio (2.4, 5 or 6 GHz). Each row is a radio; the bar covers the channels
it occupies (an HT40 radio covers more than an HT20 one).

- **Solid green bar, "on air"**: the radio is up on that channel, with its width and TX power.
- **Dashed amber bar, "parked (staged channel)"**: the radio is off; the bar shows the channel it would use.

Use it to spot two radios on overlapping channels before a test. On a narrow window the map scrolls
sideways; hover a bar to read its full label.

## Router cards

One card per router, with a state badge:

| Badge | Meaning |
|---|---|
| **on air** | At least one radio is up |
| **parked** | Reachable, all radios off |
| **needs app key** | Added, but the app's SSH key is not installed yet |
| **unreachable** | The last connection attempt failed; the app keeps retrying, waiting longer each time (up to a minute) |
| **connecting** | Not read yet |

A card lists model and firmware, then:

- **Radio**: channel, width and TX power, or the staged channel and "radio off".
- **Stations**: count, and per station signal and TX/RX rates.
- **Network**: LAN address and whether this router runs the DHCP server.
- **Login**: "app key · host key pinned" when all is set.

When the app has faults armed on a router, the card also shows **N faults armed**, which opens
[Faults and capture](Faults-and-capture). The count comes from the fault records on the router, so it stays
right after the app restarts.

**Open** goes to the router's overview; **Terminal** opens a shell on it.

## Needs attention

Below the cards, anything that needs you:

- **no app key yet**: **Install key** finishes the wizard for that router.
- **host key changed**: the router presents a different SSH key than the pinned one, usually after a
  reflash. **Check and re-pin** opens the wizard to compare and pin the new key.
- **unreachable since hh:mm**: with the last error.

## Router list

The left column (top on narrow windows) lists every router with its state, and **+ Add router**.

## Router overview

**Open** on a card, or a router in the list, shows that router's overview. **What … says about itself**
is what the router reported when the app connected, read from the sources LuCI uses: `board.json`, the
ubus services, the typed Wi-Fi option lists, feature flags and the LuCI menu. **Ports** shows each
internal switch port with its printed label and the label saved for this router. **Probe again** reads
it all once more; **Open terminal** opens a shell on the router.

The row of buttons under the title opens the router's other screens: [Wi-Fi](Wi-Fi), RF live,
[Network & DHCP](Network-and-DHCP), [Ports & VLANs](Ports-and-VLANs), [Firewall](Firewall),
[Faults & capture](Faults-and-capture) and the terminal, then every LuCI page
that has no screen in the app yet.
