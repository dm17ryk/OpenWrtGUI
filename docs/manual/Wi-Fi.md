# Wi-Fi

The Wi-Fi screen sets what a router's radio sends and how, then proves it on air. Open it from a router's
sections (**Wi-Fi**) or its overview.

![Wi-Fi](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/wifi.png)

## Radio tabs

One tab per radio. The bench routers have one 2.4 GHz radio; 5 and 6 GHz tabs are shown greyed out when the
router has no such radio. The badge next to the title says whether the radio is on air, and on which channel
and width.

## Modes

**Auto** lets the router decide (no overrides). **All** allows 802.11b, g, n at 20 MHz and n at 40 MHz. Or tick
modes: the router then uses only the ticked ones, in both directions.

- **802.11b** only: CCK rates 1, 2, 5.5 and 11 Mb/s.
- **802.11g** only: OFDM rates 6 to 54 Mb/s, no CCK, no HT.
- **802.11n** only: data at HT rates; beacons and management frames still go out at 6 Mb/s OFDM, because
  802.11 needs a legacy basic rate.

Auto leaves `legacy_rates` as it is (a harness may have set it), so on this image Auto has no 802.11b rates
unless `legacy_rates` is 1. Ticked modes also set a TX rate mask with `iw`, which lives only until the next
Wi-Fi reload; see "TX mask after a reload".

## Channels

**Auto** picks any allowed channel, **All** picks among every allowed channel, **None** parks the radio (it stops
sending). Or tick channels: one ticked channel is fixed, several let the router pick among them. The allowed
channels come from the router for its country; channel 14 is not allowed in IL.

Taking a radio off None puts it on air. If its SSID is already on air on another router, the preview warns
you: the bench rule is one radio on air per SSID.

## TX power

**Auto** uses the regulatory maximum. **Fixed** sets the power in dBm. The screen shows the power you asked for
next to the power the driver reports. A power cap is offered only on radios whose driver can use one; the
bench routers' rt2800 radio cannot.

## SSID and security

Change the SSID and choose Open, WPA2-PSK, WPA3-SAE or WPA2 + WPA3. WPA3 choices are offered only when the
router's hostapd supports SAE. The key is never shown: leave the field empty to keep it, or type a new one
(8 to 63 characters, or 64 hex digits). Keys are hidden in the preview and the audit log.

## Apply and proof on air

The preview shows the exact commands the app will send; only settings that change are written. The first
line, `set -e`, makes the router stop at a failing line, so a half-done change is never committed; the radio
reload runs on its own after the commit. If the router changed since the preview (LuCI, another program),
Apply is refused with "changed since the preview" and the new preview shows what would be sent now.
**Apply** sends the commands, waits for the radio to settle, sets the TX mask, and then checks on air:

- the radio is up (or parked, for None);
- the channel and width;
- the TX power;
- the TX mask;
- the beacon rate, read from real beacons through a temporary monitor interface.

A change counts as done only when these checks pass. If the connection drops while the change runs, or a
harness run starts after it was committed, the result says "Applied, not verified" with the reason (a dropped
connection may or may not have let the commit through; the screen reads the router again). While a harness run is live,
Apply is refused and the banner names the run.

## TX mask after a reload

The TX rate mask is a runtime setting: any Wi-Fi reload (by a harness, LuCI or by hand) removes it. When that
happened, the screen says "TX mask not active". Press **Apply** again to restore it; nothing else is sent.

## Stations

The stations on each SSID: MAC, name and IP (from the router's host hints), signal, TX and RX rate, mode and
connected time. **RF** opens RF live for that station. **Block** disconnects it and keeps it out for the
number of seconds you choose (10 to 3600). **Deauth** disconnects it; it may join again at once. Both are
refused during a harness run.

## Who may join

One line per SSID: **Everyone**, **Block listed** or **Only listed**, with how many devices are on its saved list
(for example "Block listed · 2 devices"). The lists, and blocking one device now, for N seconds or saved, are
changed on Network & DHCP › Wi-Fi access by MAC; the link under the summary opens it.

## All options

Every option the radio and its SSIDs accept, from the router's own list (`network.wireless get_validate`): on
the bench routers 155 radio options and 289 SSID options. Search, show only the options set in the config,
or only those a harness sets (for example `cell_density` by dima_night). An empty value means "not in the
config": the driver default applies. Options with their own control above say so. Edits go through the same
preview, Apply and check.

## Step-through

Steps the radio through every ticked mode × ticked channel × ticked TX power, one pure mode per step, in the
order mode (b, g, n20, n40), then channel, then power (no power ticked: the power stays as it is). At most
200 steps. Each step is an Apply of exactly that mode, channel and power, proven on air like any Apply,
beacon rate included; only then does the step wait.

- **Timer** waits the dwell (10-3600 s) after the proof. **Manual** waits for **Next step**. **Station
  re-joins** waits until the chosen station (by its MAC) is associated and authorized again, records how long
  that took (from the step's start: the reload drops it), then dwells; a station that is not back within the
  re-join limit (30-600 s after the proof) is recorded "not re-joined" and the run goes on.
- The preview shows every step's exact commands and the restore at the end, before **Start step-through**,
  with how long the run takes: about that long on a timer, at most that long when a station re-joins (each
  step counted with its whole re-join limit). The run checks each step against the preview: if someone
  changed the radio meanwhile, it stops and restores.
- A step whose proof fails is recorded "not proven" and the run goes on, without its wait. A refused change
  or a lost connection stops the run and restores the radio.
- Before step 1 the radio's mode, channel and power options are saved in the data folder. At the end, on
  **Stop and restore** and when the app closes, they are applied back, proven, and the saved copy goes. If the
  app ended before that, **Restore** is offered here and on the dashboard.
- When a harness run starts, the step-through stops at once and leaves the radio as it is, since a Wi-Fi
  reload would disturb the run. **Restore** works again once Bench Guard is clear.
- While a step-through runs, Apply, All options, the saved MAC lists, a channel scan, a reboot, a restore and
  a flash of this router wait for it. It does not start while one of the radio's SSIDs is on air on another
  router.

## Step-through results

One row per step: mode, channel, TX power, whether it was proven on air (or which checks failed), the beacon
rate heard, and the station's re-join time. The same rows go to a CSV in `Documents\OpenWrtGUI\` as each step
ends (`steps-<router>-<radio>-<time>.csv`), so a crash keeps what was done.
