# Install

## What you need

- Windows 10 or 11, 64-bit.
- Microsoft Edge WebView2 Runtime. Windows 11 has it. Without it the app still works, in your default
  browser (see [Troubleshooting](Troubleshooting)).
- Nothing else: Python and every library are bundled in the installer.

## Steps

1. Download `OpenWrtGUI-Setup-<version>.exe` from the
   [Releases page](https://github.com/dm17ryk/OpenWrtGUI/releases). Pick the newest release that is not
   marked *Pre-release*, unless you want CI builds (see [Updating](Updating)).
2. Run it. It installs for your Windows user only; no admin rights are needed.
3. **Install folder**, where the program goes.
4. **Data folder**, where the app keeps the router list, pinned host keys, its SSH key, the audit log and
   settings. It must be a folder of its own: new, empty, or the data folder of an earlier install. The
   installer refuses a drive or a folder that already holds other files. Updates keep it; uninstalling
   asks before deleting it.
5. Finish. The app starts, and adds a Start-menu entry (and a desktop icon if you ticked it).

The installer proposes these folders; you can change both:

| On a PC that has | Install folder | Data folder |
|---|---|---|
| `C:\Essence_SC` | `C:\Essence_SC\apps\OpenWrtGUI` | `C:\Essence_SC\apps\OpenWrtGUI-data` |
| only `D:\Essence_SC` | `D:\Essence_SC\apps\OpenWrtGUI` | `D:\Essence_SC\apps\OpenWrtGUI-data` |
| neither | `%LOCALAPPDATA%\Programs\OpenWrtGUI` | `%LOCALAPPDATA%\OpenWrtGUI` |

> **On the Essence bench PCs (SentinelOne)** keep **both** folders inside `C:\Essence_SC\` or
> `D:\Essence_SC\`; the proposed folders already are. SentinelOne stops programs started from other
> folders without any message.

An update installs into the folder you chose the first time.

## Silent install

For scripted installs:

```bat
OpenWrtGUI-Setup-0.1.0.exe /VERYSILENT /DIR="C:\Essence_SC\apps\OpenWrtGUI" /DATADIR="C:\Essence_SC\apps\OpenWrtGUI-data"
```

## Uninstall

Windows Settings → Apps → OpenWrtGUI → Uninstall. You are asked whether to delete the data folder too;
the default is to keep it. When you say yes, the app's routers, settings, keys, backups, audit log, downloaded
updates and log are deleted, then the folder itself if nothing else is left. A silent uninstall never deletes the
data folder.

- **Yes** deletes `routers.json`, `settings.json`, `known_hosts`, `keys\`, `audit\`, `updates\`, `logs\` and
  `backups\` (the routers' backups hold password hashes and Wi-Fi keys).
- If a program still has a file open in the backups or keys folder, that folder cannot be deleted. The
  uninstaller then says which folders are still there; delete them by hand.
- `exports\`, `profiles\`, `reflash\`, `tools\` and `steps\` stay, and so does the folder while they are in it:
  delete them by hand if you no longer need them.

## Running more than once

Only one copy runs at a time. Starting it again shows "OpenWrtGUI is already running."
