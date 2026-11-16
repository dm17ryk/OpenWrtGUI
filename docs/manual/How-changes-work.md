# How changes work

Every change the app makes on a router follows the same path:
1. You see the exact commands first.
2. The app sends them.
3. It checks on the router that the change took effect.

This page explains that path once. Each screen's page says what that screen checks.

## Preview

Before anything is sent, a change shows its **Command preview**: the exact commands, one per line, that the app
will run on the router. Only settings that change are written. If the router changed since the preview (in LuCI
or another program), the app refuses and shows the new preview. Wi-Fi, for example, says "changed since the
preview". Nothing is sent until you press the button under the preview.

## Apply with rollback

Some changes can cut the app off from the router: addresses, bridges, VLANs, routes and the firewall. They apply
with a **60 s rollback**, the same way LuCI applies them:
1. The router keeps a copy of its settings.
2. The app connects again and checks the change.
3. Only then does the app confirm it.

If the app cannot reach the router within 40 s, the router puts its previous settings back by itself 60 s after
the change, and the app checks that they are back. While it waits, the card says "Applying with a 60 s rollback:
waiting for … to answer". The details are in [Network and DHCP](Network-and-DHCP#rollback). If a router does not
come back, see [Troubleshooting](Troubleshooting#a-router-that-does-not-come-back-after-a-rollback).

Other changes are read back after they are sent. A change counts as done only when the router shows it.

## Proof on air

A Wi-Fi change counts as done only when the radio shows it on air. The app checks:
- that the radio is up (or parked, if you chose None);
- the channel and the width;
- the TX power and the TX mask;
- the beacon rate, read from real beacons.

The result then says "Applied and proven on air". The result says "Applied, not verified", with the reason, in
two cases:
- the connection drops;
- a harness run starts after the change was committed.

The details are in [Wi-Fi](Wi-Fi#apply-and-proof-on-air).

## Refused

A refused change sends nothing to the router, and the screen says why. The common reasons:

- **A harness run is live.** The refusal names the run, for example "dima_night.py started 21:04 (PID 18244)".
  See [Bench Guard](#bench-guard) below.
- **The router is busy.** A router runs one job at a time: a reboot, a restore or a reset. A second job is refused,
  naming the first: the router "is already rebooting", "is restoring a backup" or "is resetting to defaults".
  Wait for that job to end.
- **Something the change needs is missing.** The control is greyed and says what is missing, for example a program
  the router does not have.
- **The change would cut this app's own connection.** Examples are deleting the interface the app talks through,
  or turning off the switch port it uses. These are refused with the reason, or they apply only with the
  rollback.

## Bench Guard

While a test harness runs on the bench, every router is read-only in the app. Reads keep working. Every write is
refused, and the refusal names the run. [Bench Guard](Bench-Guard) says what it watches and what still works
during a run.

## The audit log

Every command the app sends to a router is recorded in the [audit log](Terminal-and-audit-log#audit-log), with
passwords and keys masked. You can see later exactly what was sent, to which router, and when.
