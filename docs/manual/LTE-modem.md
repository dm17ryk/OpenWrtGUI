# LTE modem

The LTE screen shows a router's LTE modem (the BroadMobi BM806C on the bench routers): whether it is
registered, the signal, the data session, and the modem's own details. It also connects and disconnects the
session, reboots the modem safely, changes the LTE settings with rollback, and has an AT console. Open it from
the router's sections, or from the LTE interface's row on [Network and DHCP](Network-and-DHCP).

![LTE modem](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/lte.png)

A router without a qmi interface in its network config has no LTE screen content: the screen says so and
shows nothing else.

## Status

**Registration** (registered, searching, not registered, denied), **radio** (LTE, UMTS, GSM), roaming, the
**operator** with its MCC and MNC, the data session (up with its uptime, connecting, or down), the session's
IPv4 address and the bytes received and sent. The operator name comes from the modem's AT port; when the
AT port does not answer it comes from QMI and says "(from QMI, may be garbled)", because the BM806C sometimes
returns that name with wrong characters.

When a part of the modem does not answer, the screen names it ("No answer from the modem for: signal") and
shows the rest.

## Signal quality

The four LTE values, each with a label from common LTE field thresholds; a value on a boundary gets the better
label.

| Value | Excellent | Good | Fair | Poor |
|---|---|---|---|---|
| RSRP (dBm) | -80 or more | -90 to -80 | -100 to -90 | below -100 |
| RSRQ (dB) | -10 or more | -15 to -10 | -20 to -15 | below -20 |
| SNR (dB) | 20 or more | 13 to 20 | 0 to 13 | below 0 |
| RSSI (dBm) | -65 or more | -75 to -65 | -85 to -75 | below -85 |

RSRP and SNR say the most: RSRP is how strong the cell's reference signal is, SNR how clean it is. RSSI
includes noise and other cells, so a good RSSI with a poor SNR means interference.

## Live signal

RSSI, RSRP, RSRQ and SNR over the last minute, 5 minutes or hour, one sample every 10 seconds while the screen
is open. A sample the modem does not answer is a gap in the lines and a note, not a change of state. Reading
the signal changes nothing, so the charts keep working during a harness run.

## Settings

The APN, authentication (none, PAP, CHAP or both), user name, password, SIM PIN (4 to 8 digits), PDP type
(IPv4, IPv6 or both), MTU, metric, **Bring up at boot** and **Default route**. Every other option of the LTE
interface is under **All options**. The password and PIN fields start empty and show as `<hidden>` in the
preview and the audit log; leave them empty to keep what the router has.

A change runs like every interface change on Network and DHCP: the preview shows the exact commands, and the
router rolls back by itself unless the app reaches it again and confirms.

Two options stay as they are:

- **autoconnect**: this image's qmi.sh turns the modem's autoconnect off at every connect, so the setting has
  no effect.
- **DHCP on lte_4**: lte_4 must stay DHCP, because the BM806C sends downlink only after a DHCP exchange binds
  the router's MAC.

## Modem

Manufacturer, model and firmware (from `AT+CGMI`, `AT+CGMM`, `AT+CGMR`), the operating mode, and the
network mode order the modem reports (`AT+BMMODODR?`; the numbers are not mapped to names yet). The IMEI
shows as dots until you press **Reveal**; it is read from the modem then and never stored, logged or written to
the audit log.

## Connect, disconnect, reboot

- **Connect** brings the session up (`ifup lte`) and waits up to 60 seconds for it. If the carrier has not
  given lte_4 an address yet, the result says "no address yet: waiting for the carrier's DHCP"; that is not a
  failure.
- **Disconnect** takes the session down (`ifdown lte`). Devices that route through it lose the internet until
  it is back.
- **Reboot modem** sets the modem to low power, checks it, sets it online, checks it, and brings the session
  up again. It never uses the modem's reset mode: on the BM806C that wedges the modem until a power cycle. If
  the modem does not come back online the result says so; then use Connect again or power-cycle the router.

Each shows its commands before it runs, one action at a time per router, and none runs during a harness run.
Reset to factory defaults is not offered yet (open item O1).

## AT console

Type an AT command (printable text starting with AT, at most 200 characters) and press **Send**; the answer
shows with its status (OK, ERROR or no answer). Up and Down recall the last 50 commands. Every command goes
to the audit log.

Queries (`AT`, `ATI`, `AT+CSQ`, `AT+CGMI`, `AT+CGMM`, `AT+CGMR`, and any `AT+<name>?` or `AT+<name>=?`)
cannot change the modem and work any time, also during a harness run. Any other command may change the modem:
the console asks "This command may change the modem. Send it?" first, and it is disabled during a run.
