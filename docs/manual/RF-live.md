# RF live

RF live shows, once a second, what a router's radio and each connected station see. Blue is always
RX at the AP (station → AP); orange is always TX from the AP (AP → station). It reads the router only while
the screen is open, and nothing it does changes the router, so it keeps working during a harness run.

LuCI's **Status › Realtime Graphs › Wireless** page opens here: RF live shows the same live rate, signal and noise,
per station and per radio.

![RF live](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/rf-live.png)

## Radio

The tiles show the channel and width, the TX power asked for next to the power the driver reports, how busy the
channel is (the share of time the radio heard something), the noise floor, and ACK failures per second. A
value the driver does not report says "not reported": the bench routers' rt2800 radio gives no noise floor
and no ACK signal, and its busy time has no RX/TX split.

## RX at AP

What the AP receives from the chosen station: signal now and averaged, per antenna, the RX rate and mode,
packets and bytes per second, drops, and how long ago the last frame arrived.

## TX from AP

What the AP sends to the chosen station: the TX rate with its MCS, width and guard interval, the share of
frames retried, failed frames per second, the expected throughput, packets and bytes per second, and the ACK
signal where the driver reports one.

## Charts

**Signal** and **Data rate** over the last minute, 5 minutes or hour. Hover a chart for the value at that
moment. **Pause** freezes the charts; the samples keep arriving and the charts catch up when you resume. A
station that leaves is marked "left" and its lines stop.

## Which rates reach the station

From the router's rate control (minstrel): for each rate, how often the AP tried it, how many frames the
station acknowledged, and which rate is in use now. It needs a station on the radio and the router's debug
file system; until the bench check of this file (open item O6) is done, the table says it is not available yet.

## Record to CSV

**Record to CSV** writes one row per station per second to `Documents\OpenWrtGUI\` (the file name has the
router, the radio and the start time). **Stop recording** closes the file; leaving the screen stops it too.

## Frame analysis

Off by default, and only for a radio on air. **Frame analysis…** shows the commands first: it adds a monitor
interface (`owgmon0`) on the radio, asks it for frames with a bad checksum too, and runs `tcpdump` for 3 s of
every 5 s. The router only prints the frames; the app counts them. Blue is RX at the AP (frames stations sent
to it), orange is TX from the AP (frames it sent):

- **Rate mix**: which rates (or MCS) the frames went at, per direction.
- **RX signal**: how strong the frames from stations were, in 5 dB steps. The AP's own frames carry no signal.
- **Retry flag**: the share of frames marked as a retransmission. The TX retry share from the station counters
  is shown beside it, since the router's own sent frames rarely carry the flag.
- **Bad FCS**: the share of all frames heard that arrived broken, or "not reported" when the radio does not
  pass them on.

The last window and the totals since the start are shown side by side. It costs the router CPU, so it stops
by itself after 30 minutes, when you leave RF live, and when a harness run starts (the monitor interface is
removed). A Wi-Fi Apply or a step-through step reloads the radio and removes the monitor; frame analysis adds
it again and says so. Starting it is refused while a harness run is live.

## Channel analysis

**Scan…** shows the command, then **Scan now** listens on every channel in turn (a passive scan: nothing is
sent). On a radio on air the AP leaves its channel for about 2 s, so its stations may miss traffic meanwhile;
on a parked radio the app adds a temporary interface for the scan and removes it again.

The chart shows each network heard as a span over the channels it occupies (20 or 40 MHz), as high as its
signal, the router's own in orange, and under it each channel's busy share during the scan. The table lists
the networks: SSID ("(hidden)" when it is not broadcast), BSSID, channel, width, signal and security, sortable
by signal, channel or SSID. The last scan is kept until the app closes. A scan is refused while a harness run
is live or a step-through runs on the router.
