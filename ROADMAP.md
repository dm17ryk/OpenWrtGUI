# Roadmap

Milestones; the order can change. Each milestone gets its own implementation plan. Progress is tracked
in [GitHub milestones](https://github.com/dm17ryk/OpenWrtGUI/milestones).

| Milestone | Content |
|---|---|
| v0.1 Foundation | Repo setup (README, templates, AGENTS.md, CI, pre-release and release workflows, wiki sync), installer, update check, app shell with themes, Add-router wizard (password → key), router self-description probe, router list, read-only dashboard, Bench Guard, audit log, terminal |
| v0.2 Wi-Fi and LuCI fallback | Wi-Fi screen (selectors, TX power, security, apply + verify on air, All options from the typed list), stations, RF live (radio and stations, charts, CSV); LuCI fallback pages (after O13), so every LuCI page is reachable from here on |
| v0.3 Network | Router addresses with rollback (fields from the proto handlers), DHCP, fixed addresses, Wi-Fi access by MAC, DNS, routes; ports/VLANs/mirroring (swconfig, labels from `board.json`) |
| v0.4 Firewall and faults | Both filtering models, zones, rules, port forwards, NAT, IP sets, custom rules, other tables with unlock; faults and capture |
| v0.5 Discovery and images | Image import and profiles, overlay difference, custom tools panel, flash firmware from image |
| v0.6 LTE and System | LTE screen (status, settings, actions, AT console), System screen (all LuCI System and Status pages) |
| v0.7 Test helpers | Step-through runner, `mon0` frame analysis, channel analysis |
| v1.0 | Native screens for every LuCI page on the bench image (the fallback stays for pages that later images bring), manual complete, hardening |
| 1.x (phase 2) | Tool pages, SIM PIN / SMS / USSD, DSA backend and 5/6 GHz checked on real hardware |

The full design is in [docs/superpowers/specs/2026-11-03-openwrt-gui-design.md](docs/superpowers/specs/2026-11-03-openwrt-gui-design.md).
