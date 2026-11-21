# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] — 2026-11-21

First release. The protocol is at version 1 and the wire format is documented in
[docs/protocol.md](docs/protocol.md).

### Added

- `BridgeServer`: a loopback TCP server that queues incoming code onto Blender's
  main thread via `bpy.app.timers`. Socket threads never touch `bpy`.
- `BridgeClient`: standard-library-only client with `ping`, `status`, `exec`,
  `exec_or_raise`, `run_file`, and `screenshot`.
- `bpy-bridge` CLI with `ping`, `status`, `exec`, `shot`, `token`, and
  `token-path`, plus `--json` output and documented exit codes.
- Persistent exec namespace across requests, with a `bridge` helper injected
  (`status`, `shot`, `exec_file`, `bpy`).
- Response `kind` field so clients never have to pattern-match error strings.
- Random 256-bit token (`secrets.token_urlsafe`), persisted with `0600` on
  POSIX, compared with `secrets.compare_digest`.
- Loopback-only bind by default; non-loopback addresses raise unless
  `allow_remote=True` is passed explicitly.
- 4 MiB frame cap in both directions.
- Per-request timeout with a distinct `timeout` kind.
- 117 tests, runnable without Blender, using a fake `bpy` module.
- `tests/standalone_server_check.py`, which proves `server.py` works with no
  package around it.
- `tests/e2e_smoke.py`, which drives a real bridge in a separate process
  through the installed CLI and asserts on exit codes.
- Bilingual documentation: `README.md` (English, default) and
  `README.zh-CN.md` (Simplified Chinese), each with a language switcher.
- `tests/check_readme_links.py`, which verifies the switcher exists in both
  files and that every relative link resolves to a real path.

### Known limitations

- No cancellation: a timed-out job keeps running on Blender's main thread.
- One request per connection; concurrency comes from multiple connections.
- `shot()` requires a GUI session.

[Unreleased]: https://github.com/YOUR-USER/bpy-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/YOUR-USER/bpy-bridge/releases/tag/v0.1.0
