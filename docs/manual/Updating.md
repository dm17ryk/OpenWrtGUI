# Updating

OpenWrtGUI updates itself from the project's
[GitHub Releases](https://github.com/dm17ryk/OpenWrtGUI/releases).

![Settings, with the Updates section at the top](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png)

## When it checks

At start-up and once a day, unless you switch off **Check at start-up and daily** in
[Settings](Settings). **Check now** checks immediately. The Updates section says when it last checked,
or "Not checked yet."

## Channels

- **Stable**: releases such as `0.1.0`.
- **Pre-release (CI builds)**: also every green build of `master`. A CI build carries the version being
  worked on and a build number, for example `0.2.0-ci.42`: newer than `0.1.0`, older than the `0.2.0`
  release. Useful for trying a fix before it is released. Only the newest ten CI builds are kept on GitHub.

## Installing an update

When a newer version exists, Settings shows its name, size and release notes, with three buttons:

- **Update now** downloads the installer and `SHA256SUMS.txt`, checks the SHA-256, then closes the app,
  installs into the same folder, and starts the new version. If a terminal is open, you are asked first.
- **Skip this version** stops offering that version; a newer one is offered again.
- **Later** hides the offer until the next check.

While an update is waiting, an **Update available** pill in the top bar links to Settings.

## Going back

The previous installer is kept in the data folder. **Reinstall previous version** (in Settings, once
there is one) installs it again.

## Running a development build

A build you ran from source (not the installed app) shows offers but cannot install them: "Updates
install only in the installed app."
