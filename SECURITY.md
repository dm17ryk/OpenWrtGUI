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
| `profiles\` | Imported router images and what the app read from them |
| `reflash\` | Reflash checklists |
| `tools\` | Promoted tool cards |
| `steps\` | The saved radio options of a step-through that has not been restored yet |

RF recordings, step-through results and captures go to `Documents\OpenWrtGUI`.

The app **never stores router passwords**. The root password you type in the Add-router wizard is used
for that one login, to install the app key, and is then discarded.

## What the app exposes

The UI and the local API listen on `127.0.0.1` only, on a random port, and every request needs a token
created at launch. Nothing listens on the network. The app makes outgoing connections to your routers
(SSH) and to `api.github.com` / GitHub release downloads (update check).

Updates are downloaded over HTTPS and checked against the release's `SHA256SUMS.txt` before the
installer runs. The installer is not Authenticode-signed yet.
