# Adding a router family

A standard OpenWrt router works on first connect: the app reads what the router says about itself, as LuCI
does. Importing the router's firmware image adds what the live read cannot see: which files and packages came
with the image, the bench's own packages with their usage text, the config defaults, and the image to flash.

## Import the image

In [Settings](Settings#images), **Import image…** and pick the router's sysupgrade `.bin`. The app reads it on
this PC (nothing is sent to a router): the kernel header, the squashfs root file system and the image's metadata,
which names the boards it is for. The profile is kept by board, revision and the image's sha256, with a copy of
the image, so a later flash does not depend on the original file.

An image that cannot be read is refused with the reason (not a sysupgrade image, no root file system, a
compression the app cannot read).

## Build from a router's /rom

When no image file is at hand, **Build from this router's /rom** on [Discovery](Discovery#image) reads the
router's read-only root file system and builds the same profile, without file hashes. It cannot check the
firmware or flash: import the image file for that.

## After importing

Every router with that board and revision matches the profile. Its [Discovery](Discovery) screen then shows what
changed since flashing, and the Dashboard counts files added after flashing.
