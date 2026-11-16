# Image library: find and download supported firmware from GitHub (0.8.2)

Date: 2026-11-16. Status: design, for Dmitry's review.

## Intent

When a router has no imported image, Discovery shows only "No imported image for <board> <revision>" with
**Import image…** and **Build from this router's /rom**. Everyone who installs the app then has to find the right
sysupgrade `.bin` by hand, although the firmware the bench runs is already published.

The app should find that firmware by itself. It looks up the router's board and revision in the releases of
Dmitry's public firmware repository, [dm17ryk/openwrt](https://github.com/dm17ryk/openwrt), and offers to download
and import the matching sysupgrade image in one click. After that, Discovery, **Check firmware** and **Flash** work
as they do for an imported image today.

Dmitry wants this shipped as release **0.8.2**, cut from the v0.8.1 tag like the 0.8.1 hotfix, with master
getting it too.

## What exists today

- **The firmware releases.** `dm17ryk/openwrt` (a public fork of openwrt/openwrt) builds and releases the bench's
  firmware with its own workflow ("Build and release DWR-921 C3 U-Boot firmware"). Release `v25.12.5`
  ("DWR_921-c3-uboot-qmifix3", 2026-10-06) is the build the bench runs, `r35692-b8bffeefdf`. Among its assets:
  - `openwrt-ramips-mt7620-dlink_dwr-921-c3-uboot-squashfs-sysupgrade.bin` (11,272,478 bytes);
  - `sha256sums`;
  - OpenWrt's own `profiles.json` (metadata_version 1). It gives `version_code` (`r35692-b8bffeefdf`) and,
    per device profile, `supported_devices` (`["dlink,dwr-921-c3-uboot"]`) and `images[]` with `type`
    (`sysupgrade`, `factory`, `kernel`), `name`, `sha256` and `size`.
  - Other files that are not OpenWrt images for these routers (D-Link stock firmware, a PDF, guides, an
    unrelated board's images).
- **How the app matches an image.** `ProfileStore.match(board, revision)` (`src/openwrtgui/images/store.py`)
  compares the router's `board_name` with each profile's `key.board` and the revision with `key.revision`.
  `key.board` is the first board in the image's own metadata (fwtool `supported_devices`), not every entry of
  `profile.boards`; Flash, by contrast, accepts any entry of `profile.boards`. If several imported profiles match,
  `match` prefers one from an image over one from `/rom`, then the newest import. In `profiles.json` the same
  strings appear: `supported_devices[]` holds board names and `version_code` the revision.
- **Import.** `POST /api/images` takes the raw bytes; `ProfileStore.import_image(data, name, now)` builds the
  profile from the image and stores `profile.json` plus a copy of the image under
  `<data>/profiles/<board>/<revision>-<sha256[:12]>/`. The limit is `MAX_IMAGE` (64 MB).
- **Downloading from GitHub.** The app's updater (`src/openwrtgui/update/github.py`, `installer.py`) already
  reads the public releases API anonymously, streams an asset and refuses it unless its SHA-256 matches the
  release's sums file.
- **The screens.** Discovery's Image card (`frontend/src/screens/discovery/ImageSection.tsx`) and
  Settings › Images (`frontend/src/screens/ImagesSection.tsx`).

## Goals

1. On Discovery, a router with no matching image shows whether the image library has its exact build (same
   board, same revision). This includes a router matched only by a profile built from its `/rom`. If the library
   has the build, one button downloads and imports it.
2. Settings › Images lists every image the library offers for these routers, with its board, revision, release,
   size and whether it is already imported, and can download any of them. This is how a person gets a different
   build to flash.
3. A new firmware release in `dm17ryk/openwrt`, published by its workflow with its `profiles.json`, appears in
   the app with no change to OpenWrtGUI.
4. Released as 0.8.2 from the v0.8.1 tag, and merged into master.

## Non-goals

- Publishing images from the app. Publishing stays in the `dm17ryk/openwrt` workflow.
- Images from anywhere else: upstream `downloads.openwrt.org`, vendor stock firmware, other repositories. The
  repository is fixed in the code (`dm17ryk/openwrt`), not a setting.
- Flashing straight from the library. An image is downloaded and imported first; Flash then offers it like any
  imported image.
- Library entries for `/rom` profiles.
- GitHub tokens, private repositories or rate-limit workarounds beyond caching.
- Signatures beyond SHA-256 (see Constraints).
- A progress bar for the download.

## Anti-goals

These would make it a failure even if it works:

- **Downloading without a click.** Nothing is downloaded until the person presses the button: an image is 11 MB.
- **Discovery waiting on GitHub.** The library lookup is a separate request. Discovery renders from the router as
  today, and the library line fills in when GitHub answers. GitHub being slow or unreachable never delays or
  breaks the Discovery read.
- **Keeping a file that is not what the catalog said.** A download whose SHA-256 differs from `profiles.json`, or
  whose own board or revision (read by the import) differs from the catalog entry, is refused and nothing is
  stored.
- **Touching a router.** Looking up and downloading never sends anything to a router, so both work while Bench
  Guard shows a run.

## Constraints

- **Version 0.8.2** (Dmitry's choice, although a new feature would usually bump the minor). The README's
  per-minor rule does not ask for a new "What v0.x adds" section for a patch release.
- **Network.** Reads `https://api.github.com/repos/dm17ryk/openwrt/releases` anonymously, like the updater, with
  the same `User-Agent`. GitHub allows 60 anonymous API requests per hour per IP, and bench PCs may share one.
- **Trust.** HTTPS to GitHub, plus the SHA-256 given by the same release's `profiles.json`. This catches a corrupt
  or swapped download, not a compromised repository. Flash still runs its own checks before writing
  (`validate_firmware_image`, `sysupgrade -T`, the board check).
- **Sizes.** `profiles.json` at most 1 MB. An image at most `MAX_IMAGE` (64 MB), checked against the catalog's
  `size` before downloading and while streaming.
- **The simulator and CI never reach GitHub.** In simulator mode GitHub is the simulator's stand-in
  `simulator.sim_http_client`, the updater's mock. Today it answers any path ending in `/releases` with the
  updater's `tests/fixtures/github/releases.json`, so it must be split by repository: `dm17ryk/openwrt/releases`
  gets a fake firmware release whose `profiles.json` describes the simulator's image
  (`tests/fixtures/images/mini-r35692.bin`, loaded in `simulator.py`), and that asset's URL returns those bytes.
  e2e tests and CI stay offline and deterministic.
- **The firmware workflow keeps attaching `profiles.json`** and the sysupgrade image to each release. A release
  without `profiles.json` is not in the library. This goes in the manual's "Adding a router family".

## Approaches considered

- **A. Read the firmware releases directly** (chosen by Dmitry, 2026-11-16). The app lists the releases of
  `dm17ryk/openwrt` and reads each release's `profiles.json` as the catalog. Nothing new to maintain: the firmware
  release is the source of truth. It finds only images released with a `profiles.json`.
- **B. A hand-kept catalog file in OpenWrtGUI** (`images.json` with board, revision, SHA-256 and a link). One
  request, and it can point anywhere, but every new firmware needs an edit and a PR to OpenWrtGUI, and a missed
  edit means the app does not know about it.
- **Not considered further:** committing `.bin` files to git (or Git LFS), and a separate images repository. Both
  duplicate what the firmware releases already publish.

## Design

### The catalog

A library entry is one sysupgrade image (one SHA-256), from the newest release that has it:

| Field | From |
|---|---|
| boards | the device profile's `supported_devices`, in order. The entry is offered to a router whose board equals the first one, because that is the board an imported image is matched by (`key.board`). Changing `match` to look at every board is out of scope. *(My call.)* |
| revision | `profiles.json` `version_code` |
| target | `profiles.json` `target` (shown, not matched) |
| title | the profile's `titles[0]`: vendor, model, variant |
| image name, sha256, size | the profile's `images[]` entry with `type == "sysupgrade"` |
| download URL | the release asset with that exact name (`browser_download_url`) |
| release | tag, name, published date, HTML URL |

- An image entry whose asset is missing from the release is left out. If GitHub's asset `digest` is present and
  differs from the `profiles.json` SHA-256, the entry is left out too.
- The same image (same SHA-256) in several releases is listed once, under the newest release.
- Read the newest 100 releases (one API page). Drafts are not visible anonymously. Pre-releases are included and
  marked as such.
- The catalog is cached in memory for 10 minutes. Settings › Images has **Refresh**, which reads again at once.
- **Errors** are reported, not hidden. Two cases with their own text:
  - GitHub unreachable or timing out: "The image library on GitHub could not be reached: <reason>."
  - The rate limit (HTTP 403 with `X-RateLimit-Remaining: 0`): "GitHub's limit for anonymous reads is reached;
    try again after <time from X-RateLimit-Reset>."

  A release whose `profiles.json` cannot be read or parsed is skipped and counted ("1 release could not be
  read").

### Download and import

1. Look up the entry in the current catalog by its SHA-256. An unknown SHA-256 is refused.
2. Refuse if a profile with that SHA-256 is already imported, with today's "already imported" message.
3. Stream the asset into memory, up to the entry's `size` and never more than `MAX_IMAGE`.
4. Compare the SHA-256 with the catalog's. A mismatch: "<name> does not match its release's profiles.json;
   nothing was imported."
5. Import through `ProfileStore.import_image`, the same code as **Import image…**. If the profile it builds has a
   `key.board` other than the entry's first board, or a different revision, delete the new profile and refuse.
6. Record where it came from: `Profile` gains `origin: str | None` (the release URL, default None so existing
   `profile.json` files still load).
7. Clear the discovery summaries, as `POST /api/images` does.

- One download per SHA-256 at a time. A second request for the same image while one runs gets "already
  downloading".
- A cut download stores nothing.

### API

- `GET /api/images/library` returns the catalog entries plus the read time, the skipped-release count, and an
  error text if the read failed. Each entry carries whether it is already imported, by SHA-256. Optional
  `board` and `revision` query parameters filter to an exact match, which Discovery uses.
- `POST /api/images/library/refresh` re-reads at once.
- `POST /api/images/library/{sha256}` downloads and imports, and returns `ProfileOut` like `POST /api/images`.
- `ProfileOut` gains `origin`.

### Discovery (Image card)

The library line shows in two cases:
- **No matching profile.** The note and the two buttons stay, with the library line underneath.
- **The match is a profile built from `/rom`.** "Matches … (built from this router's /rom)" stays, and the library
  line offers the image, because Check firmware and Flash need it. After the download, `match` already prefers the
  image over the `/rom` profile. *(My call.)*

Here is the first case, with the library line filled in from the separate query:

```text
No imported image for dlink,dwr-921-c3-uboot r35692-b8bffeefdf. Import its sysupgrade image (Settings › Images),
or build a profile from this router's /rom.

Image library: D-Link DWR-921 C3 (U-Boot), r35692-b8bffeefdf, 11.3 MB, release DWR_921-c3-uboot-qmifix3
[Download and import]   [Import image…]   [Build from this router's /rom]
```

- While the lookup runs: "Looking in the image library…". With no exact match: "The image library has no build
  for <board> <revision>." On an error: the error text. In both cases the other two buttons work as today.
- While downloading, the button reads "Downloading 11.3 MB…" and every button in the card is disabled. When it
  finishes, the card refreshes and shows the normal "Matches …" view.
- **Several builds of one revision.** A rebuild from the same source commit with a different configuration keeps
  the revision but changes the image. When the library has more than one image (different SHA-256) for the
  router's board and revision, Discovery offers the one from the newest release and adds "N other builds of this
  revision are listed in Settings › Images; Check firmware tells whether the router runs the one you
  downloaded." `match` keeps its tie-break (the newest import) when several imported images match. *(My call.)*

### Settings › Images

A new **Image library** part under the imported images:

- A table of entries: title, board, revision, release (linked, with "pre-release" when marked), size, and either
  **Download** or "Imported".
- **Refresh** and the time of the last read.
- The skipped-release count and errors, as on Discovery.
- An imported profile that came from the library shows "from the image library: <release>" next to its name.

### Documentation

- The manual's Discovery (Image), Settings (Images) and Adding a router family pages. The last one says how an
  image gets into the library: a release in `dm17ryk/openwrt` with its `profiles.json` and sysupgrade image.
- Help topics for the new buttons, in the app's existing help style.
- CHANGELOG: a `[0.8.2] - <date>` section, added on master the way #71 added `[0.8.1]`.

### Release 0.8.2

This follows the 0.8.1 path:

1. The feature is built on `feat/image-library` from master, and goes to master in its own PR, with the CHANGELOG
   `[0.8.2]` section and link references.
2. `release/v0.8.2` is cut from the `v0.8.1` tag. The feature commits are cherry-picked onto it, conflicts
   resolved there (master has changed `discovery/state.py`, `discovery/service.py` and `images/profile.py` since
   v0.8.1). The release branch must also carry the CHANGELOG `[0.8.2]` section: `release.yml` builds the notes
   with `tools/release_notes.py`, which fails when the tagged commit has no `## [0.8.2]` section. On 0.8.1 it
   arrived with the cherry-picked fix commit, so put the section in a commit that is cherry-picked too. Then the
   six version files go to 0.8.2:
   - `src/openwrtgui/version.py`;
   - `pyproject.toml`;
   - `uv.lock`;
   - `frontend/package.json`;
   - `frontend/package-lock.json`;
   - `installer/OpenWrtGUI.iss`.
3. The full gate runs on the release branch. The annotated tag `v0.8.2` triggers `release.yml`. The release
   branch is not merged; master stays 1.0.0-dev.
4. Pushing, the PR, the tag and the release each need Dmitry's go.

### Testing

- **Unit tests for the catalog parser.** They use the real `profiles.json` of release v25.12.5 as a fixture (it
  is public). Cases:
  - one entry per supported board;
  - the factory and kernel images are ignored;
  - a missing asset leaves the entry out;
  - a digest that disagrees leaves it out;
  - the same SHA-256 in two releases is listed once;
  - a bad `profiles.json` is skipped and counted;
  - an oversized `profiles.json` is refused.
- **The download.** An `httpx.MockTransport` GitHub serves both the catalog and the asset. Cases:
  - a correct download imports, and `origin` is set;
  - a SHA-256 mismatch stores nothing;
  - an asset over its size stores nothing;
  - a cut stream stores nothing;
  - a board or revision that differs from the entry removes the new profile;
  - a second concurrent request is refused;
  - an already imported image is refused;
  - the 403 rate-limit message names the reset time;
  - the cache serves a second read within 10 minutes, and Refresh bypasses it.
- **API tests** for the three endpoints, plus a check that the Discovery read makes no request to GitHub.
- **More catalog cases:** a device profile with two supported boards gives one entry, offered only for the first
  board; two different images for one board and revision offer the newest and count the other.
- **Frontend (vitest):**
  - the Image card's library line in each state (looking, match, none, error, downloading), and with a `/rom`
    match;
  - Settings › Images with the library table.
- **e2e against the simulator:** a router with no profile shows the library match; **Download and import** turns
  the card into "Matches …".
- **Not tested automatically:** the real GitHub API. Once on a bench PC, after 0.8.2 is installed: open AP2's
  Discovery and download its image from the library. This is read-only for the router.

## Calls made without Dmitry

A fresh reviewer read this design as its builder would. These are the calls I made on what it asked; each is
marked *(My call.)* above.

1. **Several builds of one revision:** Discovery offers the newest and counts the others; Check firmware tells
   which one the router runs.
2. **Images that list several boards:** one entry per image, offered only to a router whose board is the first
   listed, as imported images are matched today.
3. **A router matched only by a `/rom` profile** is offered the library image too.

## Left to the builder

- Module layout (for example `src/openwrtgui/images/library.py` for the catalog and download, reusing the
  updater's streaming code where it fits).
- The cache's exact shape and the lock per SHA-256.
- Copy details beyond the texts given here, in the app's plain style.
- Task order, and how the cherry-pick conflicts on `release/v0.8.2` are resolved.
