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
- `examples/inspect_scene.py` and `examples/collection_report.py`, both runnable
  against any open scene.
- 127 tests, runnable without Blender, using a fake `bpy` module.
- `tests/standalone_server_check.py`, which proves `server.py` works with no
  package around it.
- `tests/e2e_smoke.py`, which drives a real bridge in a separate process
  through the installed CLI and asserts on exit codes.

### Documentation

- Bilingual documentation: `README.md` (English, default) and
  `README.zh-CN.md` (Simplified Chinese), each with a language switcher.
- [docs/tutorial.md](docs/tutorial.md) and its
  [Chinese translation](docs/tutorial.zh-CN.md): an eight-step walkthrough built
  on a real production scene (5,757 objects, 45 collections), with screenshots.
- [docs/configuration.md](docs/configuration.md) and its
  [Chinese translation](docs/configuration.zh-CN.md): every knob, its default,
  and what changing it does.
- `tools/render_terminal.py` and `tools/screenshots.json`: the documentation
  screenshots are **build artifacts**. Each one runs the real command against a
  live Blender session, captures stdout/stderr/exit code, and draws the result.
  Re-running the script regenerates every image, so the docs cannot drift from
  the code.
- `tools/render_architecture.py`: the thread-boundary diagram, generated rather
  than hand-drawn.
- `tests/check_readme_links.py`, which verifies every bilingual pair cross-links
  near the top of both files, that every relative link in every doc resolves,
  and that every image the tutorial references exists.

### Fixed

All four were found by running the real commands against a live 5,757-object
scene, which is the only way they could have been found.

- **`bpy` was missing from the exec namespace.** The README's headline example,
  `bpy-bridge exec 'len(bpy.data.objects)'`, raised
  `NameError: name 'bpy' is not defined` because only `bridge` was injected.
  Documentation that shows a command which fails is worse than no documentation.
  `bpy` is now injected lazily on first execution, so the obvious snippet works.
- **A trailing expression evaluating to `None` returned the string `"None"`.**
  `repr(None)` is `"None"`, which is noise in `--json` output and forces every
  consumer to special-case it. A Python REPL prints nothing for `None`; this now
  matches that and returns `null`.
- **`status` printed every collection name on one line.** On a 45-collection
  scene that is an unreadable wall of text. It now shows a count plus a bounded
  preview, with the full list still available via `--json`.
- **The e2e script decoded child pipes with the host locale encoding.** On a
  Chinese Windows install that is GBK while the CLI emits UTF-8, so the reader
  thread raised `UnicodeDecodeError` — and `subprocess` swallows exceptions from
  its reader threads, so the script still reported `exit 0` while silently
  losing the stderr text it asserts on. Its failure detection was broken exactly
  where it mattered. Both pipes are now pinned to UTF-8.

### Changed

- `start()` now forwards every `BridgeServer` option (`max_frame_bytes`,
  `namespace`, `persist_token`) instead of a curated subset. A facade that cannot
  express a supported setting is how documentation starts describing parameters
  that do not exist.

### Known limitations

- No cancellation: a timed-out job keeps running on Blender's main thread.
- One request per connection; concurrency comes from multiple connections.
- `shot()` requires a GUI session.
- `docs/protocol.md`, `docs/security.md`, and `docs/install.md` are English-only
  for now; the Chinese README says so rather than pretending otherwise.

[Unreleased]: https://github.com/YOUR-USER/bpy-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/YOUR-USER/bpy-bridge/releases/tag/v0.1.0
