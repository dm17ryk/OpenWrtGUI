# Settings

**Settings** in the top bar holds everything about the app itself (not the routers).

![Settings](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png)

## Updates

Installed version, the update channel (**Stable** or **Pre-release (CI builds)**), **Check now**, and
**Check at start-up and daily**. When an update is offered: **Update now**, **Skip this version**,
**Later**. See [Updating](Updating).

## Appearance

**System** (follows Windows light or dark), **Light** or **Dark**. The choice is saved at once and applies to
every screen, the charts included; with **System** the app follows Windows' own setting. The moon button in the
top bar switches between light and dark directly.

## Folders

The data folder in use, and **Open data folder** to show it in Explorer. On the Essence bench PCs keep it
inside `C:\Essence_SC\`; the installer proposes `C:\Essence_SC\apps\OpenWrtGUI-data` there (see
[Install](Install)).

The app looks for its data folder in this order: the `OPENWRTGUI_DATA` environment variable, the folder
chosen at install (stored under `HKCU\Software\OpenWrtGUI`), then `%LOCALAPPDATA%\OpenWrtGUI`.

## Bench Guard

The watch list: **Lock files**, **Processes on this PC** and **SSIDs on air on a router**. While any of them is
live, every router is read-only. The defaults are this bench's harnesses (such as `dima_night.py`,
`voip.lock.own` and the run SSIDs); remove one with the **×** on its chip, and add one with the field below.
Changes are saved at once. See [Bench Guard](Bench-Guard).

## Known devices

Devices by name with every MAC address they use. A panel's Ethernet and Wi-Fi MAC addresses are unrelated, so
the [Faults](Faults-and-capture#target) screen finds a device by any of its MACs, never by vendor prefix. Add one
here (a name and its MACs, separated by commas or spaces) or with **Remember as** on the Faults screen.

## Known tables

nftables tables, or chains inside fw4's table, that a harness writes, with its name and what depends on them. The
[Firewall](Firewall#other-nftables-tables) screen shows them with that owner and keeps them locked until you
unlock one. It starts with `BENCHSIPGUARD` (dima_night) and `bridge voipdscp` (the VoIP chain).

## Images

The firmware images imported on this PC, and profiles built from a router's `/rom`, each by board and revision,
with the size and the bench's own packages it holds. **Import image…** reads a sysupgrade `.bin` (see
[Adding a router family](Adding-a-router-family)); **Delete** removes the profile and its copy of the image.
A router whose board and revision match a profile shows how it differs on [Discovery](Discovery).

## Image library

Every image the library offers for these routers, read from the releases of `dm17ryk/openwrt` on GitHub. Each row
shows the board, the revision, the size and the release it comes from (marked **pre-release** when it is one).
**Download** fetches the image, checks it against its release and imports it, like **Import image…** above; the
row then says **Imported**. Nothing is downloaded until you click. **Refresh** reads the releases again; **Read
at** shows when they were last read. A release whose `profiles.json` cannot be read is only counted ("1 release
could not be read"). An image imported from the library shows a **from the image library** link to its release
in [Images](#images).

## App SSH key

The app's own key (ed25519), created on first start. Shown with its fingerprint; **Export public key**
saves `openwrtgui.pub`, for example to add it to a router by hand. The private key never leaves the data
folder and is readable by your Windows user only.

## Audit log

How long to keep the [audit log](Terminal-and-audit-log): **30 days**, **90 days** (default),
**1 year** or **Forever**. The log is one file per day in the data folder's `audit\` folder; each time the app
starts, it deletes the days older than this. **Forever** deletes nothing. Exports already saved in `exports\` are
not touched.

## About

The version and licence (for example `OpenWrtGUI 1.0.0 · GPL-3.0`), a link to the project on GitHub, and
**Quit**, which closes the app and its local server. Give this version when you report a problem in
[Issues](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose).
