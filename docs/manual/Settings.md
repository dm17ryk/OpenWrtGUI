# Settings

**Settings** in the top bar holds everything about the app itself (not the routers).

![Settings](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png)

## Updates

Installed version, the update channel (**Stable** or **Pre-release (CI builds)**), **Check now**, and
**Check at start-up and daily**. When an update is offered: **Update now**, **Skip this version**,
**Later**. See [Updating](Updating).

## Appearance

**System** (follows Windows light or dark), **Light** or **Dark**. The moon button in the top bar
switches between light and dark directly.

## Folders

The data folder in use, and **Open data folder** to show it in Explorer. On the Essence bench PCs keep it
inside `C:\Essence_SC\`; the installer proposes `C:\Essence_SC\apps\OpenWrtGUI-data` there (see
[Install](Install)).

The app looks for its data folder in this order: the `OPENWRTGUI_DATA` environment variable, the folder
chosen at install (stored under `HKCU\Software\OpenWrtGUI`), then `%LOCALAPPDATA%\OpenWrtGUI`.

## Bench Guard

The watch list: lock files, processes on this PC, and SSIDs on air on a router. While any of them is
live, every router is read-only. See [Bench Guard](Bench-Guard).

## App SSH key

The app's own key (ed25519), created on first start. Shown with its fingerprint; **Export public key**
saves `openwrtgui.pub`, for example to add it to a router by hand. The private key never leaves the data
folder and is readable by your Windows user only.

## Audit log

How long to keep the [audit log](Terminal-and-audit-log): **30 days**, **90 days** (default),
**1 year** or **Forever**.

## About

The version and license, a link to the project, and **Quit** (closes the app and its local server).
