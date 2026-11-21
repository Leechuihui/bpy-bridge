## What this changes

<!-- One paragraph. What behaviour is different after this PR? -->

## Why

<!-- The problem. Link the issue if there is one: "Fixes #12". -->

## How it was verified

<!-- Check what applies. The first two are expected for almost every PR. -->

- [ ] `pytest -q` passes
- [ ] Added a test that fails without this change
- [ ] `python tests/standalone_server_check.py` passes (required if `server.py` changed)
- [ ] Tried it against a real Blender session
- [ ] Docs updated (`docs/protocol.md`, `README.md`, `CHANGELOG.md`)

## Contract check

<!-- These are the project's load-bearing invariants. Tick honestly. -->

- [ ] `server.py` still has no non-stdlib imports and no relative imports
- [ ] No new code path touches `bpy` outside the main-thread pump
- [ ] No new runtime dependency
- [ ] Wire format unchanged, or `docs/protocol.md` updated and `protocol` bumped
- [ ] Default bind address is still loopback

## Screenshots / output

<!-- Optional but helpful for anything user-visible. -->
