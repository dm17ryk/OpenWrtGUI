# Discovery

Shows how a router differs from the firmware image it was flashed with: files and packages added after
flashing, settings changed from the image's defaults, and whether the firmware itself still matches. It lists the
bench's own (custom) packages and programs with their usage text, lets you run a program's `--help`, turn a
program into a card of named commands, and start, stop or restart custom services. From here you can also copy
files to another router and flash the router with an imported image.

Discovery needs the router's image: import its sysupgrade file in [Settings](Settings#images), or build a profile
from the router's own `/rom` (see [Adding a router family](Adding-a-router-family)). What the router says about
itself (board file, services, LuCI pages) stays on the router's **Overview**.

![Discovery: what AP1 changed since flashing](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/discovery.png)

## Image

The image this router matches, by board and revision. With no match, **Import image…** and **Build from this
router's /rom** are offered. A profile built from `/rom` has no image file, so it cannot check the firmware or
flash.

## Firmware check

**Check firmware** hashes the router's firmware partition and compares it with the same bytes of the image: equal
means the router runs exactly that build. It reads about 11 MB of flash, which takes a few seconds of the
router's CPU, so it runs only when you press it and not while [Bench Guard](Bench-Guard) shows a run.

## Flash this image

**Flash an image…** opens the flash dialog. Pick one of the imported images for this router's board (the dialog
offers one whose revision differs from the running one). The preview lists every step before anything is sent:
the image goes to `/tmp/owg` on the router, its sha256 is checked, the router validates it
(`validate_firmware_image` and `sysupgrade -T`), and `sysupgrade` is started by a timer on the router two seconds
later. The router is off the network for about three minutes; once `sysupgrade` starts it cannot be stopped.
**Flash** stays grey until you type the router's name (its short name, such as `AP2`, is enough).

The dialog then shows the upload, **Checking the image on …**, **Starting sysupgrade**, **Waiting for … to come
back** with the time so far, and **Checking the new firmware**. A reflash checklist is saved first, and the flash
is reported done only when the router answers again with the new board and revision. After a flash that kept
settings, **Copy back lost files** lists the files the checklist saved, all ticked, and copies them back to the
router with the usual preview. **Flash again** sets the finished flash aside and shows the form again, for
example to flash the router back to the image it had.

**Keep settings** (on by default) keeps `/etc/config`, the SSH host keys and the app's key, so the app reconnects
by itself; the app also keeps its own saved firewall files (`/etc/owg`). Without it, the router comes back as
192.168.1.1 with no password and no key, which clashes with AP1: confirm that the router is isolated from the
bench LAN first, then connect it alone to this PC and add it again; the wizard accepts its new host key only when
the board and revision it reads match the image you flashed.

The image must name this router's board, there must be room for it in the router's RAM, and nothing is flashed
while Bench Guard shows a run.

## Added after flashing

Files in the router's overlay that the image does not have (**added**), files it changed (**changed from the
image**) and image files it deleted, plus packages installed, removed or upgraded since. Each file shows whether
a flash that keeps settings keeps it or loses it. A name that cannot be read is counted, not shown.

## Copy files

Tick files and pick a router in **Copy to** (any router the app has a key for, this one included). The preview
shows each file with its size and sha256; **Copy** sends them and proves each copied file by reading its sha256
back. Files up to 1 MB each and 4 MB in
all; a router's own keys and password files (`/etc/shadow`, `/etc/dropbear`, `/etc/owg`) are never copied to
another router.

## Reflash checklist

**Save as reflash checklist** keeps what this router added after flashing and the files a flash would lose, with
their contents, so you can copy them back afterwards. One is also saved before every flash.

## Config changed

For each config the image has a default for, the options the router changed (image value and router value).
Configs the router made at first boot, such as `network` and `wireless`, are listed by name only: there is no
image default to compare with, and their values (Wi-Fi keys among them) are not read.

## Your custom packages

Packages with neither a license nor a URL: the bench's own, such as `dwr921-portctl`. Each shows its version,
description and programs with the usage text read from the image, and one of: a link to the screen of this app
that already drives it (such as **Ports screen** for `dwr921-portctl`), **card below** (you promoted it),
**service** with its state (driven from Custom services), or **no card yet** with **Run --help** and **Promote**
on each of its programs.

## Programs and services

Programs added after flashing that no package owns (a script copied by hand), in the same form as custom
packages: usage text, then **Run --help** and **Promote** until it has a card.

## Run help

Runs `<program> --help` on the router for at most 5 seconds and shows what it prints. A program that does not
know `--help` may do something else, so it is previewed, refused during a run and recorded in the audit log.
**Promote from this output** fills a card from what it printed instead of the usage line.

## Promote to a card

Turns a program into named commands with checked parameters, filled in from its usage line: the first `{a|b|c}`
group gives one command per choice, later groups become choice parameters. Edit each command's label and
arguments (words; a parameter goes in as `{name}`), its parameters (a choice list, a text pattern or a number
range) and **Changes the router**: every command counts as a change until you untick it. A read-only command
runs without taking the router's write lock, but it still waits while [Bench Guard](Bench-Guard) shows a run:
the app cannot check that a custom program only reads. **Save card** checks the card and keeps it per board, so
every router with that board shows it.

A card has one button per command; pick one, fill in its parameters, check the exact command in the preview and
**Run** it; what it printed is shown below. **Edit** reopens the card, **Remove** (twice) deletes it.

## Custom services

The init scripts of custom packages and those added after flashing: the package they come from, running and
enabled state, with **Start**, **Stop** and **Restart**, each previewed and proven by reading the state back. They
wait while Bench Guard shows a run. Every other init script, and enabling or disabling one at boot, is on
[System › Services](System#services).
