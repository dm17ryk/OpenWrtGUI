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
3. **Install folder.** Default `%LOCALAPPDATA%\Programs\OpenWrtGUI`.
4. **Data folder.** Where the app keeps the router list, pinned host keys, its SSH key, the audit log and
   settings. Default `%LOCALAPPDATA%\OpenWrtGUI`. Updates keep it; uninstalling asks before deleting it.
5. Finish. The app starts, and adds a Start-menu entry (and a desktop icon if you ticked it).

> **On the Essence bench PCs (SentinelOne)** install **both** folders inside `C:\Essence_SC\`, for example
> `C:\Essence_SC\apps\OpenWrtGUI` and `C:\Essence_SC\apps\OpenWrtGUI-data`. SentinelOne stops programs
> started from other folders without any message.

## Silent install

For scripted installs:

```bat
OpenWrtGUI-Setup-0.1.0.exe /VERYSILENT /DIR="C:\Essence_SC\apps\OpenWrtGUI" /DATADIR="C:\Essence_SC\apps\OpenWrtGUI-data"
```

## Uninstall

Windows Settings → Apps → OpenWrtGUI → Uninstall. You are asked whether to delete the data folder too;
the default is to keep it. When you say yes, only the app's own files and folders in it are deleted.

## Running more than once

Only one copy runs at a time. Starting it again shows "OpenWrtGUI is already running."
