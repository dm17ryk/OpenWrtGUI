# First router

Adding a router takes five steps. Afterwards the app logs in with its own SSH key; it never stores the
router's password.

![The Add router wizard, first step](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/add-router.png)

Before you start: the router runs OpenWrt, SSH (dropbear) is on, and this PC can reach it.

## 1. Where is the router?

Open **Add router**, type the **Router address** (for example `192.168.1.2`) and, if it is not 22, the
**SSH port**. **Connect**.

## 2. Check the router is the one you mean

The app shows the router's SSH host key: key type and fingerprint. Compare the fingerprint with the
router itself if you can (serial console: `dropbearkey -y -f /etc/dropbear/dropbear_ed25519_host_key`).
**Accept and pin** stores it; from then on the app refuses to talk to anything presenting another key.

If the address had a different key pinned before, the wizard says so. A reflash makes a new key; anything
else means you may not be talking to your router.

## 3. Log in once with the root password

Type the **Root password** and **Log in**. It is used for this one login only.

- Already have a key that works on the router? Choose **Use a key file I already have** and point to it.
- If the router has no root password yet, the wizard says so and offers to **Set a root password** first.

## 4. Install the app's key

The wizard shows the exact command it will run. It appends the app's public key to
`/etc/dropbear/authorized_keys` only if the line is not there yet, so nothing else changes and nothing
restarts. **Install key**, and the app logs in again with the key to prove it works ("app key installed
and working"). Password login keeps working as before.

The command is recorded in the [audit log](Terminal-and-audit-log).

## 5. What is this router, and its sockets

The app reads the router's self-description, the same files and ubus methods LuCI uses: model, firmware,
services, Wi-Fi options. Give the router a **Name** (for example `AP2 · office`).

**Map the sockets** proposes a printed label for each internal switch port from the router's
`board.json`, for example port 0 → `LAN4`, port 4 → `WAN`. Change a label if your sockets are printed
differently, then **Save port map**.

## Afterwards

The router appears on the [Dashboard](Dashboard) and in the router list. Its overview page shows what it
said about itself and the saved port map.

![Router overview: what AP2 says about itself](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/router-overview.png)

A router you added without finishing the key step shows **needs app key** on the dashboard, with an
**Install key** button.
