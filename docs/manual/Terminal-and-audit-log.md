# Terminal and audit log

## Terminal

**Terminal** in the top bar, or **Terminal** on a router card, opens a shell on a router. Pick the
router from the list; routers without the app key cannot open one.

![Terminal on AP2](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/terminal.png)

- **Normally** you get a full interactive shell, the same as `ssh root@<router>`, logged in with the app
  key.
- **During a harness run** ([Bench Guard](Bench-Guard) is red) the terminal switches to a read-only
  command line: type a **Command**, **Run**, and read the output with its exit code (`[exit 0]`).
  Commands that only read run (`cat`, `logread`, `iw dev`, `uci show`, `ubus call … status`, …).
  Anything that could change the router is refused with "only read-only commands run during a harness
  run".

Every command is written to the audit log.

## Audit log

**Audit log** in the top bar lists every command the app sent on your behalf: the wizard's steps, any
write, and every line typed in the terminal. The dashboard's routine 5-second reads are not listed.

![Audit log](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/audit-log.png)

| Column | Meaning |
|---|---|
| Time | When it was sent |
| Router | Which router |
| Screen | The screen it came from |
| Command | The command, with secrets masked (passwords and keys show as `<hidden>`) |
| Exit | The exit code; empty for lines typed in the full shell, where the app does not see one |
| Source | `wizard`, `terminal`, `user` (a write you confirmed) or `app` (something the app did on its own) |

Filter by **Router**, by **Text**, and by **Since** (a date).

**Export for a bug report** saves `openwrtgui-audit.zip` with one file per day, holding what this page
shows: every secret masked, including in entries an older version wrote. Attach it to a
[bug report](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose). Check it first if your router
names or addresses are private.

The log is kept for 90 days by default; change that in [Settings](Settings).
