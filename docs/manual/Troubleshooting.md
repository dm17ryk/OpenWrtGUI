# Troubleshooting

## "The host key of 192.168.1.x changed"

The router presents a different SSH host key than the one pinned when you added it. The app stops
talking to it, and the dashboard lists it under **Needs attention** as *host key changed*.

- **After a reflash or a factory reset** this is expected: the router made a new key. Click
  **Check and re-pin**, compare the new fingerprint with the router (serial console:
  `dropbearkey -y -f /etc/dropbear/dropbear_ed25519_host_key`) and **Accept and pin**. A reflash also
  removes the app key, so install it again in the same wizard.
- **If nothing was reflashed**, do not re-pin. Something else may be answering on that address (a
  duplicate IP, a different router plugged in). Check the cabling and the address first.

## A router shows "unreachable"

The app retries on its own, waiting a little longer each time (up to a minute). The card and
**Needs attention** show the last error and since when. Check, in order:

1. Can this PC reach it? `ping 192.168.1.2` from a command prompt.
2. Is the PC's network adapter on the router's subnet (for example `192.168.1.x/24`)?
3. Is SSH running on the router (dropbear) and on the port you entered?
4. Did someone remove the app key from `/etc/dropbear/authorized_keys`? Then the error says
   authentication failed; add the router again to reinstall the key.

## The wizard asks for a password although the router has my key

The wizard tries `id_ed25519`, `id_ecdsa` and `id_rsa` from `%HOME%\.ssh` and from your Windows
profile's `.ssh`, as the user `root`. It skips:

- keys protected by a passphrase (it cannot unlock them, and does not use an SSH agent);
- keys with other file names or in other folders;
- a `.ssh` folder Windows does not let the app enter. A profile `.ssh` that is a junction (for example to
  `C:\Essence_SC\home\.ssh`) can be one: Windows may refuse to follow it for the app ("untrusted mount
  point") although `ssh` in a terminal follows it. Set `HOME` so `%HOME%\.ssh` is the real folder, or
  choose the key file yourself.

For those, choose **Use a key file I already have** in the login form and point to the file, or log in
with the password once and let the app install its own key.

## A router that worked now says "The key file … cannot be used"

That router logs in with a key from this PC (it was already trusted when you added it), and the file has
since been moved, deleted or given a passphrase. Put the file back, or add the router again: the wizard
then finds another way in, or installs the app's own key.

## The app opens in my browser instead of its own window

The app window needs the Microsoft Edge WebView2 Runtime. Without it, the app opens in your default
browser instead and works the same. To get the window back, install the
[WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (Evergreen) and restart
the app. Closing the browser tab does not stop the app; use Settings → **Quit**.

## The installer or the app does nothing (Essence bench PCs)

SentinelOne on the bench PCs stops programs that run from outside `C:\Essence_SC\` or `D:\Essence_SC\`,
without a message. Uninstall, then install again with both the app folder and the data folder inside
`C:\Essence_SC\`, for example `C:\Essence_SC\apps\OpenWrtGUI` and `C:\Essence_SC\apps\OpenWrtGUI-data`
(the installer proposes these when `C:\Essence_SC` exists). Also run the installer itself from a folder
inside `C:\Essence_SC\`.

## "OpenWrtGUI is already running."

Only one copy runs at a time. Look for its window, or its tab in your browser. If it is really gone,
end `OpenWrtGUI.exe` in Task Manager and start it again.

## Writes are refused

A harness run is live, so every router is read-only. The red banner in the top bar names it. Wait for it
to end, or check the watch list in Settings if the banner names something that is not really a run.
See [Bench Guard](Bench-Guard).

## A router that does not come back after a rollback

The app says "Not applied" and the `restored` check failed: the router did not answer at its old address 65 s
after a network change.
1. Wait until 2 minutes after the change. rpcd's rollback puts the previous settings back at 60 s.
2. Power-cycle the router. After the rollback, its flash holds the previous settings, so it boots with them. Do
   not power-cycle during the first 60 s: then the flash still holds the change.
3. If it still does not answer, use OpenWrt's failsafe mode: power it on, press a button when the LED blinks fast,
   and reach it at its failsafe address (192.168.1.1) with a cable. Run `firstboot` only if you mean to reset every
   setting.

If the app says instead that the router answers but its saved settings differ from before the change, do not
reboot it: a reboot loads those settings. Check them on the Network screen or in LuCI first.

## The router is busy

A router runs one job at a time. When a router is busy, a second job is refused with the job that holds it, and
nothing is sent for the refused one. You see, for example:
- "… is already rebooting", "… is restoring a backup" or "… is resetting to defaults" (System);
- "A flash runs on this router already" (Discovery);
- "An LTE action is already running on …" (LTE).

Wait for the first job to finish, then try again. A reboot that takes longer than 5 minutes, or a flash that
takes longer than 10, may not have come back: see the next entry. A step-through that left its radio at a step says "Restore … first";
see [A radio was left at a step-through step](#a-radio-was-left-at-a-step-through-step).

## A reboot or a flash does not come back

- **A reboot.** A router that is not back 5 minutes after a reboot is reported "not back". Check its power, its
  LEDs and the cable to this PC, then **Reconnect**. A router that still does not answer can be power-cycled: a
  reboot writes nothing to the flash.
- **A flash.** The router is off the network for about three minutes; the dialog shows **Waiting for … to come
  back** with the time so far, and waits up to 10 minutes. After that it says "… did not come back within 10
  minutes. It may still be writing flash: do not power it off; check its LEDs, then try Reconnect."
  - **Do not cut the power while the router may still be writing the flash.** Cutting it then can leave the router
    unable to start. Check its LEDs as the message says, give it more time, then try **Reconnect**.
  - **A flash that kept settings** comes back at its old address with the same host key, and the app reconnects.
  - **A flash without settings** comes back at 192.168.1.1 with no password. **Needs attention** then shows
    "Reflashed without settings: add it again".
- **If it still does not answer** once nothing is being written, power-cycle it. If that does not help, use
  OpenWrt's failsafe mode, as in
  [A router that does not come back after a rollback](#a-router-that-does-not-come-back-after-a-rollback).

## An update does not download or install

- **"Couldn't check for updates: GitHub's hourly limit for this network is used up until …"**. GitHub's API
  allows 60 reads an hour per network address, and every PC behind the same address shares them. The app
  already tried the release pages on github.com instead, and they did not answer either. Try again after the
  time shown, or use **Download from GitHub** ([Updating](Updating#downloading-by-hand)).
- **"Couldn't download the update: …"** with the reason. Either this PC could not reach GitHub, or the download
  broke off. Check the PC's internet connection (a proxy or a firewall may block `github.com` downloads), then
  **Check now** again.
- **The same message ending "does not match … SHA256SUMS.txt".** The downloaded installer is not the file the
  release lists, so the app did not run it. Try again. If it repeats, download the installer from the
  [releases page](https://github.com/dm17ryk/OpenWrtGUI/releases) and compare its SHA-256 with the release's
  `SHA256SUMS.txt` yourself.
- **"Updates install only in the installed app."** You are running a build from source.
- **The installer starts but nothing changes** (Essence bench PCs). See
  [The installer or the app does nothing](#the-installer-or-the-app-does-nothing-essence-bench-pcs).
- **To go back** to the version you had, use **Reinstall previous version** ([Updating](Updating#going-back)).

## A LuCI page does not open

- **"LuCI does not show … on …: …"** The router lacks what that page needs, such as a program or a setting. The
  page list shows the page under **Not on this router**, with what it needs.
- **"No LuCI page … on …"** The router's LuCI has no such page; a different image has other pages.
- **A page that opened and then closed by itself.** Nobody used it for 5 minutes, or a harness run started and the
  app could not switch it to read-only. Open it again.
- **LuCI itself does not answer.** Check that uhttpd runs on [System › Services](System#services); LuCI pages
  open through it.

## Wireshark does not start

"Wireshark is not installed on this PC": **Live in Wireshark** needs Wireshark. The app looks for
`Wireshark\Wireshark.exe` in Program Files, then for `Wireshark` on the PATH. Install Wireshark, or use **Save .pcap**
instead: the file goes to `Documents\OpenWrtGUI\captures` and opens in Wireshark later. See
[Faults and capture](Faults-and-capture#capture).

## LTE does not connect

The session stays down, or it is up but the Status card says "no packet-data handle". Press **Recover** on the
[LTE screen](LTE-modem#recovering-the-modem): it finds what is wrong and tries one step at a time until LTE
works. If it says LTE did not come back, reboot the router, then power-cycle it.

## The LTE modem has no address

The LTE screen shows "no address yet: waiting for the carrier's DHCP". The modem is registered, but the carrier has
not given the router an address yet. Give it a minute. If it stays:
- check the APN in **Settings** on the [LTE screen](LTE-modem#settings), since a wrong APN is the usual cause;
- check the operator and signal under [Status](LTE-modem#status);
- try **Connect** again, or **Reboot modem**.

## "This screen hit an error"

One screen shows "This screen hit an error: …. The other screens still work." Or a message says
"Unexpected error in OpenWrtGUI (…). The details are in the app log." Either way, something the app did not plan
for went wrong there. Other screens and the routers are not affected.

Open the screen again from the menu. If it repeats, attach the end of the app log to a
[bug report](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose) (see [Where are the logs?](#where-are-the-logs)).

## Where are the logs?

`logs\app.log` in the data folder (Settings → **Open data folder**). Attach its end, with the audit-log
export, to a [bug report](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose).

## A radio was left at a step-through step

The Wi-Fi screen and the dashboard's **Needs attention** say so when a step-through ended before it put the
radio back: the app was closed or crashed, or a harness run started. The radio options it saved before step 1
are in the data folder (`steps\`). **Restore** applies them back, proven on air like any Apply, and removes the
saved copy; it waits while Bench Guard sees a run.

## Flash refused: not enough free memory

The app uploads the image into the router's memory first and needs the image plus 4 MiB free. On a router with
less (a router with about 8 MB of RAM), flash with LuCI's **System › Backup / Flash Firmware** or from the terminal
(`sysupgrade`).
