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
- keys with other file names or in other folders.

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

## Where are the logs?

`logs\app.log` in the data folder (Settings → **Open data folder**). Attach its end, with the audit-log
export, to a [bug report](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose).

## A radio was left at a step-through step

The Wi-Fi screen and the dashboard's **Needs attention** say so when a step-through ended before it put the
radio back: the app was closed or crashed, or a harness run started. The radio options it saved before step 1
are in the data folder (`steps\`). **Restore** applies them back, proven on air like any Apply, and removes the
saved copy; it waits while Bench Guard sees a run.
