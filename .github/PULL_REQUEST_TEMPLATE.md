## What and why

<!-- What this changes, and the problem it solves. Link the issue: "Fixes #…". -->

## How it was tested

<!-- Commands you ran; for router behaviour, whether it ran against the simulator or AP2. -->

## Checklist

- [ ] Tests added or updated, and they failed before the change
- [ ] `uv run pytest`, `uv run ruff check`, `uv run mypy`, `npm test`, `npm run lint` pass
- [ ] UI changes: screenshots in light and dark, and it still works at 375 px
- [ ] API changes: `tools/dump_openapi.py` + `npm run gen:api` re-run and `schema.ts` committed
- [ ] Every router write goes through `perform_write` (Bench Guard, write lock, audit)
- [ ] User manual (`docs/manual/`) updated if behaviour changed
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] Hardware tests, if any, ran on AP2 only with Bench Guard clear
