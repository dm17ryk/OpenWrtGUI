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

A session can be up and still carry no data: the modem then reports no packet-data handle. The card says
"Session up but no packet-data handle: the modem carries no data. Use Recover." LTE works only when the session
is up, has a packet-data handle, and lte_4 has an address.

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

If the screen loses its live connection to the app, it says "Lost the connection to OpenWrtGUI; reconnecting
(attempt N)" and tries again by itself: after 1, 2, 4 and 8 seconds, then every 15 seconds while the screen is
open. The charts keep the samples they have and go on once the connection is back.

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

**Save good setup** keeps this router's LTE options while LTE works: every option the card can edit, the
password and SIM PIN included. It is greyed while LTE does not work, and it asks before it replaces an older
setup ("Replace the good setup saved 2026-11-10?"). The setup stays on this PC, in `lte-setups\` in the
[data folder](Files-and-data), readable by your Windows user only.

**Reconfigure** puts a saved setup back as one settings change, with the preview and the rollback above:
- choose this router's setup, or another router's (by its name and the day it was saved);
- only the options that differ are changed; an option the router has and the setup lacks is removed;
- the device is never changed, and another router's setup never brings its SIM PIN: each SIM has its own;
- an option the setup has but this router does not know is named and left out; an MTU the setup lacks stays,
  since the card cannot remove it.

A setup file that cannot be read shows as "(cannot be read)" and cannot be chosen. Removing a router from the
app deletes its saved setup.

## Modem

Manufacturer, model and firmware (from `AT+CGMI`, `AT+CGMM`, `AT+CGMR`), the operating mode, and the
network mode order the modem reports (`AT+BMMODODR?`), as its number and the modem's own name for it. The IMEI
shows as dots until you press **Reveal**; it is read from the modem then and never stored, logged or written to
the audit log.

## SIM PIN

The SIM card shows whether the SIM asks for its PIN: off, needed (with the tries left), entered, or blocked. The
**Enter PIN** form appears only while the SIM asks for the PIN, and it waits while a harness run is live. The app
never keeps the PIN: the field is emptied after every try. **Enter PIN** never sends the PIN on the last try, nor
when the modem does not say how many tries are left: then enter it in a phone or the D-Link UI, so a wrong PIN does
not block the SIM. If the SIM's state cannot be read after a try, the card says the PIN was sent: check the tries
left before trying again. A blocked SIM needs its PUK, which the app does not offer. The AT console has no such
check: it sends what you type, such as `AT+CPIN=`, after its usual question.

## SMS

The SMS card lists the messages on the SIM or in the phone memory, and shows how many of the modem's places they
use. The list is read when the card opens; press **Refresh** to read it again and see new messages (it only reads,
so it works during a harness run). **Read** shows a message's sender, time, text and, for a long message sent in
parts, which part it is (for example "Part 2 of 3"), and works during a harness run, because it only reads. Tick
messages and press **Delete** to remove them: the card shows the exact command first, and deleting waits for a
harness run to end. If the list changed since the preview, the app says so and you preview again.
**Send SMS** takes a number and a text of 1 to 160 characters of the GSM basic set (letters, digits and common
punctuation; for example `@`, `$` and accented letters are refused). Its preview warns that the carrier may charge
for the message, and sending also waits for a harness run to end. The app never writes a message's text to the
audit log, only the command and the number. The number and text are locked while a send is waiting for the modem.

## USSD

The USSD card sends one code, such as `*100#`, and shows the network's reply. Press **Preview** to see the
command and the warning, then **Send USSD**. The app listens up to 35 seconds for the reply, and the AT console
waits until then, because both use the modem's AT port. USSD menus are not supported: if the network asks for
more, the app shows what it got and closes the session, and the same happens when no reply comes. If closing the session fails, the card says
so: the session may still be open. The code field is locked while the app listens. A reply the
carrier charges for is the carrier's business, so use only codes you know. Sending waits for a harness run to
end. Codes that change or unblock a PIN, set call barring or call forwarding (such as `*21#` or `#21#`), or start with `**` or `##` are refused: they are not
USSD, and they would put a PIN or a password into the command and the audit log.

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
If a harness run starts while Reboot modem has the modem in low power, the app still sets it online and
brings LTE up again, then stops and says so.

The stock firmware's "Restore modem defaults" only turns the modem's autoconnect off; it wipes nothing.
Recover's fourth step does the same.

## Recovering the modem

**Recover** brings LTE back without SSH. It first reads what is wrong (not registered, no session, a session
with no packet-data handle, no address, or settings that differ from the saved good setup). If LTE works, it
stops at once and changes nothing, and tells you when the settings differ from the saved setup (use
Reconfigure for that). Otherwise it tries these steps in order, and stops as soon as LTE works:

1. **Put back the saved setup**: only if this router has a saved good setup and its settings differ.
2. **Reconnect**: `ifdown lte`, then `ifup lte`.
3. **Clear QMI state**: `ifdown lte`, then `uqmi --sync` (it frees what the modem still holds of an old
   session), then `ifup lte`. `ifdown lte` returns before the router has finished closing the session, so it
   first waits, up to 20 seconds, until `lte` is down and no `uqmi` runs. If `lte` is not down by then, it
   skips `uqmi --sync`, says so, and still runs `ifup lte`.
4. **Turn off the modem's autoconnect**: `ifdown lte`, then `uqmi --set-autoconnect disabled`, up to 10 times
   one second apart, then `ifup lte`. This is what the stock firmware's "Restore modem defaults" does.
5. **Restart the modem**: `ifdown lte`, then Reboot modem's low power and online.

Each step starts only when no LTE setup runs: the router's own LTE connect script (`qmi.sh`) and the `uqmi` it
starts are not running. While LTE keeps failing, the router retries that setup about every 19 seconds, and a
step that cut one off could leave the modem's QMI channel failing until the router reboots. So before each step
Recover waits up to 20 seconds for a gap between retries, checking once a second. If no gap comes, the step is
skipped and says so, and the next step waits again. If LTE starts working while Recover waits, it stops there
and sends nothing more.

After each step it waits up to 60 seconds for LTE to work. The preview lists every command it may run; each
one after the first checks runs "only if LTE does not work after the step before". While it runs, the card
lists each step with its result, and the other LTE writes on this router wait for it.

- **Stop** puts back what the running step took down (the modem online, `ifup lte`), then stops.
- **A harness run** that starts during Recover gets the same two put-back lines, sent past Bench Guard and marked
  in the audit log; then Recover stops and says so.
- A step that fails (for example `uqmi --sync` gives an error) is noted and Recover goes on to the next one.
  Only a failure in **Restart the modem** ends it, saying where the modem was left.
- If LTE still does not work after the last step, Recover says so. Then reboot the router (**Reboot router** opens
  the [System](System) screen, which asks first), and power-cycle it if that does not help. Recover itself never
  reboots the router.

Recover never sends the modem's reset mode, `AT&F`, `AT&W` or `AT+CFUN`.

## AT console

Type an AT command (printable text starting with AT, at most 200 characters) and press **Send**; the answer
shows with its status (OK, ERROR or no answer). Up and Down recall the last 50 commands. A command with a SIM
PIN (`AT+CPIN=`, `AT+CLCK=`, `AT+CPWD=`) or an APN password (`AT+CGAUTH=`, `AT+QICSGP=`, `AT$QCPDPP=`) shows
everything after its `=` as `<hidden>`, here and in the audit log, and is not kept for recall; a `=?` query of
them shows as typed. Every command goes to the audit log. The console does not check the SIM's tries left: a wrong
PIN sent here spends a try, the last one too, so enter the PIN with **Enter PIN** on the SIM card instead.

Queries (`AT`, `ATI`, `AT+CSQ`, `AT+CGMI`, `AT+CGMM`, `AT+CGMR`, and any `AT+<name>?` or `AT+<name>=?`)
cannot change the modem and work any time, also during a harness run. Any other command may change the modem:
the console asks "This command may change the modem. Send it?" first, and it is disabled during a run.

`AT&F`, `AT&W` and any `AT+CFUN=` get a stronger question: "This command can erase the modem's saved profiles
or leave it unusable until the router is power-cycled. Use Recover instead. Send it anyway?"
