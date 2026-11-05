# RF live

RF live shows, once a second, what a router's radio and each connected station see. Blue is always
RX at the AP (station → AP); orange is always TX from the AP (AP → station). It reads the router only while
the screen is open, and nothing it does changes the router, so it keeps working during a harness run.

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
