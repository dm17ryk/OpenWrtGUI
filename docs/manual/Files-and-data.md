# Files and data

What the app keeps on this PC, what it writes for you to open, and what it leaves on a router.

## The data folder

You choose the data folder at install time; the default is `%LOCALAPPDATA%\OpenWrtGUI`.
[Settings › Folders](Settings#folders) shows the folder in use, and **Open data folder** opens it in Explorer.

| File or folder | Contents | When you would open it |
|---|---|---|
| `routers.json` | The routers you added: name, address, port map | Rarely: change routers in the app |
| `known_hosts` | The routers' pinned SSH host keys | To check which key a router was pinned with |
| `keys\` | The app's own SSH key pair. The private key is readable by your Windows user only | Never by hand: [Settings](Settings#app-ssh-key) exports the public key |
| `audit\` | The audit log: one file per day, every command the app sent, secrets masked | Read it in the app's [audit log](Terminal-and-audit-log#audit-log) |
| `settings.json` | Theme, update channel, Bench Guard watch list, audit-log retention | Rarely: change settings in the app |
| `updates\` | Downloaded installers (the current and the previous one) | To install a version again by hand |
| `logs\` | The app's own log | When something goes wrong: attach it to a bug report |
| `backups\` | Routers' configuration backups. They hold password hashes, host keys and Wi-Fi keys; the folder is readable by your Windows user only | To keep a backup somewhere safe; never share one |
| `exports\` | Audit-log exports (zip files), secrets masked as in the viewer | To send an export to someone |
| `profiles\` | Imported router images and what the app read from them | Rarely: manage images in [Settings](Settings#images) |
| `reflash\` | Reflash checklists | To read a saved checklist outside the app |
| `tools\` | Promoted tool cards | Rarely: manage cards on [Discovery](Discovery#promote-to-a-card) |
| `steps\` | The saved radio options of a step-through that has not been restored yet | Never by hand: the Wi-Fi screen's **Restore** uses it |

The app never stores router passwords. The root password you type in the Add-router wizard is used for that one
login, to install the app key, and is then discarded.

## Documents

Files made for you to open go to `Documents\OpenWrtGUI`. This is your Windows Documents folder, also when it is
redirected (for example to OneDrive).

- `rf-<router>-<radio>-<date>-<time>.csv`: an [RF live](RF-live#record-to-csv) recording, one row per station per
  second.
- `steps-<router>-<radio>-<date>-<time>.csv`: [step-through results](Wi-Fi#step-through-results), one row per step.
- `captures\<router>-<interface>-<date>-<time>-<id>.pcap`: a [capture](Faults-and-capture#capture) to a file, for
  Wireshark.

The app never deletes these files.

## On a router

- **The login line.** When you installed the app key, one line in `/etc/dropbear/authorized_keys` lets the app log
  in. With this PC's own key, the app adds nothing.
- **Pinned firewall rules** `owg_pin_ssh` and `owg_pin_dhcpdns`. They are added only when you make the zone that
  carries the app's SSH block traffic to the router. They stay until you remove them on the
  [Firewall](Firewall#pinned-rules) screen.
- **Firewall files** the app saved, under `/etc/owg`. They are kept across a flash with **Keep settings**.
- **An armed fault's record and timer** under `/tmp/owg`, until the fault ends. **Clear everything** on the
  [Faults](Faults-and-capture#clear-everything) screen removes faults left from a closed session. A reboot also
  empties `/tmp`.
- **A monitor or scan interface**, only while frame analysis or a channel scan runs. It is removed when they stop.

## Moving or removing

- **Another data folder.** The app looks for its data folder in this order:
  1. the `OPENWRTGUI_DATA` environment variable;
  2. the folder chosen at install;
  3. `%LOCALAPPDATA%\OpenWrtGUI`.

  To move, quit the app, copy the folder's contents to the new place, and point one of those at it.
- **Uninstall** (Windows Settings › Apps) removes the program and the data-folder setting. Then it asks "Also
  delete the data folder (routers, keys, backups, audit log)?"; the default is **No**.
  - **Yes** deletes `routers.json`, `settings.json`, `known_hosts`, `keys\`, `audit\`, `updates\`, `logs\` and
    `backups\` (the routers' backups hold password hashes and Wi-Fi keys).
  - If a program still has a file open in the backups or keys folder, that folder cannot be deleted. The
    uninstaller then says which folders are still there; delete them by hand.
  - `exports\`, `profiles\`, `reflash\`, `tools\` and `steps\` stay, and so does the folder while they are in it:
    delete them by hand if you no longer need them.
  - A silent uninstall keeps the whole folder.
- **Start again empty.** Quit the app, move the data folder away and start the app: it creates a new, empty one.
  Every router then needs to be added again.
- **Documents.** Files in `Documents\OpenWrtGUI` are never removed by the app or the uninstaller.
