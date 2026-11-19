# Updating

OpenWrtGUI updates itself from the project's
[GitHub Releases](https://github.com/dm17ryk/OpenWrtGUI/releases).

![Settings, with the Updates section at the top](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png)

## When it checks

At start-up and once a day, unless you switch off **Check at start-up and daily** in
[Settings](Settings). **Check now** checks immediately. The Updates section says when it last checked,
or "Not checked yet."

The check reads GitHub's API, which allows 60 reads an hour from one network address. Every PC behind the
office's address shares them, so they can run out. The app then reads the release pages on github.com instead,
which have no such limit. Those pages carry no release notes, so the offer shows **Release notes on GitHub**
and no size. If the pages do not answer either, the message says when GitHub's limit ends.

## Downloading by hand

**Download from GitHub** (in Settings › Updates) opens the newest stable release on GitHub, or every release
on the **Pre-release** channel. Download `OpenWrtGUI-Setup-<version>.exe` and run it: it updates the installed
app in place and keeps the data folder. The release's `SHA256SUMS.txt` lists the installer's SHA-256.

## Channels

- **Stable**: releases such as `0.1.0`.
- **Pre-release (CI builds)**: also every green build of `master` that changes the app (a change to the
  project's documentation alone makes none). A CI build carries the version being worked on and a build number,
  for example `0.2.0-ci.42`: newer than `0.1.0`, older than the `0.2.0` release. Useful for trying a fix before
  it is released. Only the newest ten CI builds are kept on GitHub.

## Installing an update

When a newer version exists, Settings shows its name, size and release notes, and links its page on GitHub
(**Release notes on GitHub**). **Update now** installs it in place
and starts it again, **Skip this version** stops offering it, and **Later** hides the offer until the next check.
In detail:

- **Update now** downloads the installer and `SHA256SUMS.txt`, checks the SHA-256, then closes the app,
  installs into the same folder, and starts the new version. If a terminal is open, or a step-through, a
  capture or frame analysis runs, you are asked first, naming each. On **OK** the app stops them before the
  installer starts: a step-through puts its radio back first (up to two minutes), a capture closes its file,
  and frame analysis removes its monitor interface. If the radio could not be put back, the Wi-Fi screen
  offers **Restore** after the update.
- **Skip this version** stops offering that version; a newer one is offered again.
- **Later** hides the offer until the next check.

While an update is waiting, an **Update available** pill in the top bar links to Settings.

## Going back

The previous installer is kept in the data folder. **Reinstall previous version** (in Settings, once
there is one) installs it again. Like an update, it first asks before it stops a step-through (its radio
restored first), a capture or frame analysis.

## Running a development build

A build you ran from source (not the installed app) shows offers but cannot install them: "Updates
install only in the installed app."
