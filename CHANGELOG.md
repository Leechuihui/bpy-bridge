# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `SECURITY.md` with the disclosure process, and `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1).
- `.github/dependabot.yml` for the CI actions and dev tooling, and
  `.editorconfig`.
- `CITATION.cff`, so the project can be cited.
- A star-history chart in both READMEs.

### Fixed

- The screenshot test hard-coded a Windows path and failed on Linux and macOS;
  it now absolutizes the expectation the way the server does.
- CI: a workflow step name containing `: ` broke YAML parsing, so no job ever
  started. Python 3.8 also moved to a pinned `ubuntu-22.04`, because
  `ubuntu-latest` (26.04) has no 3.8 in its toolcache.

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

- **Every document exists in both languages**, each pair with a language switcher:
  `README.md` / `README.zh-CN.md`,
  [tutorial](docs/tutorial.md) / [教程](docs/tutorial.zh-CN.md),
  [configuration](docs/configuration.md) / [配置](docs/configuration.zh-CN.md),
  [protocol](docs/protocol.md) / [协议](docs/protocol.zh-CN.md),
  [security](docs/security.md) / [安全](docs/security.zh-CN.md),
  [install](docs/install.md) / [安装](docs/install.zh-CN.md).
- The tutorial is an eight-step walkthrough built on a real production scene
  (5,757 objects, 45 collections), with screenshots at every step.
- The configuration reference documents every knob and its default, checked
  against the source rather than written from memory.
- `tools/render_terminal.py` and `tools/screenshots.json`: the documentation
  screenshots are **build artifacts**. Each one runs the real command against a
  live Blender session, captures stdout/stderr/exit code, and draws the result.
  Re-running the script regenerates every image, so the docs cannot drift from
  the code.
- `tools/render_architecture.py`: the thread-boundary diagram, generated rather
  than hand-drawn.
- `tools/render_demo_gif.py`: the README's demo GIF. It orbits `Cam_Main` through
  eight azimuths, one real `exec` per frame, rendering the actual scene camera.
  It records the camera transform, collection visibility and render settings
  first, restores all of them afterwards, and verifies the restore.
- `tests/check_readme_links.py`, which verifies every bilingual pair cross-links
  near the top of both files, that every relative link in every doc resolves,
  and that every image any doc references exists.
- `tests/check_docs_images.py`, which enforces a size budget on the doc images,
  verifies the demo GIF is genuinely animated (several frames, each visibly
  different from the last), and verifies every committed image is actually
  referenced by a document.

### Fixed

All of these were found by running the real commands against a live 5,757-object
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
- **The demo GIF rendered the viewport instead of the scene camera.**
  `bpy.ops.render.opengl` defaults to `view_context=True`, which renders whatever
  the viewport is currently looking at. Moving `Cam_Main` therefore changed its
  matrix and produced an identical image: the first orbit demo came out as eight
  near-identical frames (mean pixel difference 0.04-0.12, almost all of it the
  terminal strip's changing text). `view_context=False` fixes it; the same orbit
  now produces 9.45-11.16.
- **The GIF tool read `bpy._demo_original` before anything had set it.** The
  attribute is created on the first orbit call, so reading it beforehand raised
  `AttributeError`. The tool now performs a 0-degree orbit during setup, which is
  a safe no-op that also proves the helper works before the real frames start.
- **The GIF tool hid remote tracebacks.** On failure it printed only the child's
  stderr, which is empty when the remote code raises; the actual traceback lives
  in the JSON envelope's `error` field. It reported "CLI failed (exit 1)" with no
  cause, which cost real debugging time. The envelope's `kind`, `error` and
  `stdout` are now included in the message.
- **`architecture.png` was committed but never displayed.** The README's "How it
  works" section kept its old ASCII diagram while the generated image sat unused
  in the repository. Every existing check verified that *referenced* paths
  resolve; none verified that files are referenced at all, so nothing could
  notice. Both READMEs now show the diagram, and
  `tests/check_docs_images.py` fails on any committed image no document mentions.

### Changed

- `start()` now forwards every `BridgeServer` option (`max_frame_bytes`,
  `namespace`, `persist_token`) instead of a curated subset. A facade that cannot
  express a supported setting is how documentation starts describing parameters
  that do not exist.

### Known limitations

- No cancellation: a timed-out job keeps running on Blender's main thread.
- One request per connection; concurrency comes from multiple connections.
- `shot()` requires a GUI session.
- The demo GIF shows a camera orbit rather than a layer toggle. Measured against
  the real scene, hiding three of the largest scatter collections produced a
  pixel difference of exactly 0.00 -- the geometry is genuinely occluded. The
  measurement chose the demo, not the other way round.

[Unreleased]: https://github.com/Leechuihui/bpy-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Leechuihui/bpy-bridge/releases/tag/v0.1.0
