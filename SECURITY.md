# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's
[private vulnerability reporting](https://github.com/dm17ryk/OpenWrtGUI/security/advisories/new)
("Report a vulnerability" on the Security tab). Do not open a public issue.

Include the version (Settings → About), what you did, and what happened. You should get a first answer
within a week. Fixes ship as a new release; the release notes credit you unless you prefer otherwise.

## Supported versions

Only the latest release gets security fixes. The app updates itself from GitHub Releases.

## What the app stores on your PC

Everything lives in the data folder you picked at install time (default `%LOCALAPPDATA%\OpenWrtGUI`):

| File or folder | Contents |
|---|---|
| `routers.json` | The routers you added: name, address, port map |
| `known_hosts` | The routers' pinned SSH host keys |
| `keys\` | The app's own SSH key pair. The private key is readable by your Windows user only |
| `audit\` | The audit log: one file per day, every command the app sent, secrets masked |
| `settings.json` | Theme, update channel, Bench Guard watch list, audit-log retention |
| `updates\` | Downloaded installers (the current and the previous one) |
| `logs\` | The app's own log |
| `backups\` | Routers' configuration backups. They hold password hashes, host keys and Wi-Fi keys; the folder is readable by your Windows user only |
| `exports\` | Audit-log exports (zip files), secrets masked as in the viewer |
| `profiles\` | Imported router images and what the app read from them |
| `reflash\` | Reflash checklists |
| `tools\` | Promoted tool cards |
| `steps\` | The saved radio options of a step-through that has not been restored yet |

RF recordings, step-through results and captures go to `Documents\OpenWrtGUI`. The manual's
[Files and data](https://github.com/dm17ryk/OpenWrtGUI/wiki/Files-and-data) page lists the same files, with
what uninstall removes.

The app **never stores router passwords**. The root password you type in the Add-router wizard is used
for that one login, to install the app key, and is then discarded.

## What the app exposes

The UI and the local API listen on `127.0.0.1` only, on a random port, and every request needs a token
created at launch. Nothing listens on the network. The app makes outgoing connections to your routers
(SSH) and to `api.github.com` / GitHub release downloads (update check).

Opening a LuCI page from the app starts a second local server for that page, also on `127.0.0.1` and a random
port. The app's window enters it with a key made for that page, which becomes a cookie only that window holds;
every request must carry it. The server forwards to the router's own web server through the app's SSH
connection, and closes when you close the page or after 5 minutes unused.

Updates are downloaded over HTTPS and checked against the release's `SHA256SUMS.txt` before the
installer runs. The installer is not Authenticode-signed yet.

## Secrets on screen and in the log

- **The audit log** masks every command: the passwords you type, Wi-Fi keys and the other secret options by
  name, SIM PINs and APN passwords in AT commands, and LuCI session ids.
- **Discovery, Plugins and a LuCI page's change list** show a secret option as `<hidden>`: any option whose name
  contains `key`, `secret`, `pass`, `psk`, `token`, `pin` or `pwd`, and the audit log's list. Discovery still
  lists a secret that differs from the image, with both values hidden.
- **The AT console** shows a SIM PIN or an APN password as `<hidden>` and does not keep the command for Up/Down.
- **Backups** hold the router's secrets; they stay in `backups\`, readable by your Windows user only.

## How the code is checked

- CodeQL (Python, TypeScript) on every push to `master`, every pull request and weekly.
- ruff's bandit rules (`S`) on the shipped code, with every exception reasoned in place.
- `pip-audit` over the shipped Python packages and `npm audit` over the shipped UI packages, on every push, every
  pull request and weekly; Dependabot proposes updates weekly.

## Known limits

- **Signing:** the installer is not Authenticode-signed yet; SmartScreen and endpoint protection may warn.
  Updates are checked against the release's `SHA256SUMS.txt` instead.
- **App key rotation:** the app's SSH key is not rotated; replacing it is planned after 1.0.
- **LuCI over HTTPS:** the LuCI bridge supports a router that serves LuCI over HTTPS, but no bench router does,
  so it is untested on hardware.
- **Flashing from the app:** refused on a router without enough free RAM for the image plus 4 MiB (a router
  with about 8 MB of RAM); flash those with LuCI or the terminal.
- **Bench Guard** knows the harness processes and lock files you list in Settings; a writer it does not know
  about is not seen.
- **Bench routers:** the app key is installed only on the routers the bench owner chose, and no Claude GitHub
  Action runs on this repository.
