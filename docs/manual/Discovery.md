# Discovery

Shows how a router differs from the firmware image it was flashed with: files and packages added after
flashing, settings changed from the image's defaults, and whether the firmware itself still matches. It lists the
bench's own (custom) packages and programs with their usage text, lets you run a program's `--help`, turn a
program into a card of named commands, and start, stop or restart custom services. From here you can also copy
files to another router and flash the router with an imported image.

Discovery needs the router's image: import its sysupgrade file in [Settings](Settings#images), or build a profile
from the router's own `/rom` (see [Adding a router family](Adding-a-router-family)). What the router says about
itself (board file, services, LuCI pages) stays on the router's **Overview**.

## Image

The image this router matches, by board and revision. With no match, **Import image…** and **Build from this
router's /rom** are offered. A profile built from `/rom` has no image file, so it cannot check the firmware or
flash.

## Firmware check

**Check firmware** hashes the router's firmware partition and compares it with the same bytes of the image: equal
means the router runs exactly that build. It reads about 11 MB of flash, which takes a few seconds of the
router's CPU, so it runs only when you press it and not while [Bench Guard](Bench-Guard) shows a run.

## Flash this image

Flashes the router with an imported image. The preview lists every step before anything is sent: the image goes
to `/tmp/owg` on the router, its sha256 is checked, the router validates it (`validate_firmware_image` and
`sysupgrade -T`), and `sysupgrade` is started by a timer on the router two seconds later. The router is off the
network for about three minutes; once `sysupgrade` starts it cannot be stopped. A reflash checklist is saved
first. The flash is reported done only when the router answers again with the new revision.

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

Tick files and **Copy to…** another router (or this one, to copy back after a flash). The preview shows each file
with its size and sha256; each copied file is proven by reading its sha256 back. Files up to 1 MB each and 4 MB in
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
description and programs with the usage text read from the image, and one of: **card** (a screen of this app
already drives it, such as Ports for `dwr921-portctl`, or you promoted it), **service**, or **no card yet**.

## Programs and services

Programs added after flashing that no package owns (a script copied by hand), in the same form as custom
packages.

## Run help

Runs `<program> --help` on the router for at most 5 seconds and shows what it prints. A program that does not
know `--help` may do something else, so it is previewed, refused during a run and recorded in the audit log.

## Promote to a card

Turns a program into named commands with checked parameters, filled in from its usage line: the first `{a|b|c}`
group gives one command per choice, later groups become choice parameters. Every command counts as a change until
you mark it read-only; read-only commands also run during a run. Cards are kept per board, so every router with
that board shows them.

## Custom services

The init scripts of custom packages and those added after flashing: running and enabled state, with **Start**,
**Stop** and **Restart**, each proven by reading the state back. Other services come with the System screen.
