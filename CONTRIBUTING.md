# Contributing to bpy-bridge

Thanks for looking. This project is small on purpose, and the fastest way to get
a change merged is to keep it that way.

## Getting set up

```bash
git clone https://github.com/YOUR-USER/bpy-bridge.git
cd bpy-bridge
python -m pip install -e ".[dev]"
pytest -q
```

You do **not** need Blender to work on this project. The test suite carries a
fake `bpy` (`tests/fake_bpy.py`) that mimics the slice of the API the bridge
touches, plus a background thread that plays the role of Blender's main thread.
If your change works against the fake, it almost certainly works against the
real thing.

Before you open a PR:

```bash
pytest -q
python tests/standalone_server_check.py
python tests/e2e_smoke.py
python tests/check_readme_links.py
python -m compileall -q bpy_bridge tests
```

`tests/e2e_smoke.py` is the one that earns its keep. It starts a real bridge in a
separate process and drives it through the installed CLI, checking exit codes and
JSON shape. Two genuine bugs in the first draft of this project — an explicit
token never being written to disk, and the trailing expression of a
multi-statement snippet being dropped — were invisible to the unit tests and
immediately obvious to this script. If you change anything about packaging,
exit codes, or the request path, run it.

## Keeping the two READMEs in sync

`README.md` is the English default; `README.zh-CN.md` is the Simplified Chinese
translation. Both start with a language switcher that links to the other, and
`tests/check_readme_links.py` enforces that the switcher exists and that every
relative link in either file resolves.

What it cannot enforce is that the two versions say the *same thing*. So:

- **Any user-visible change goes into both files in the same PR.** A feature
  documented only in English is a bug for half the readers.
- Keep the section structure parallel — same headings, same order, same tables.
  It makes drift obvious at a glance during review.
- Translate meaning, not words. The Chinese version is allowed to phrase things
  naturally for Chinese readers; it is not allowed to omit a caveat.
- Code blocks stay identical apart from comments. Commands do not translate.
- `docs/` is English-only for now. If you translate a doc, add a `.zh-CN.md`
  sibling and link it from the language switcher rather than replacing the
  original.

## The three rules that matter

### 1. `server.py` must stay standalone

It has to be copyable into Blender and `exec()`-able with no package around it.
That means **no relative imports, no imports from `bpy_bridge.*`, and nothing
outside the standard library**. `tests/standalone_server_check.py` enforces this
in CI by copying the file to an isolated directory and running it there. If you
add an import to `server.py` and that check fails, the fix is to inline the code,
not to weaken the check.

### 2. Never touch `bpy` from a socket thread

Blender's API is main-thread only. Socket worker threads enqueue work; the
`bpy.app.timers` pump runs it. If you find yourself calling a `bpy` function from
`_Handler.handle()` or from anything reachable without going through
`self.submit(...)`, you have introduced a crash that will show up as a random
segfault weeks later. Route it through the queue.

### 3. Errors carry a `kind`, not just a message

Clients branch on `kind` (`auth`, `timeout`, `exec`, `protocol`, `internal`),
never on English text. If you add a failure mode, add a `kind` for it and
document it in `docs/protocol.md`.

## What a good PR looks like

- **A test that fails before your change.** This is the single strongest signal.
- **A sentence in the changelog** under `## [Unreleased]`.
- **Docs updated** if the wire format, CLI surface, or security posture changed.
  Those three are contracts; silently changing them is a bug.

Small is welcome. "Fixed a typo in the traceback handling" is a fine PR.

## What will be turned down

- New runtime dependencies. Both halves of this project exist partly *because*
they have none.
- Sandboxing / module allowlists / permission systems. The tool's job is to run
  your code; protecting you from your own code is a different project.
- Anything that makes the default bind address not-loopback.
- "Refactor everything into 12 modules." The current shape is deliberate.

## Reporting bugs

The most useful bug report includes:

1. Blender version (`bpy.app.version_string`) and OS.
2. Whether the bridge was started from the console or an autostart script.
3. The exact CLI invocation and the full output, including the exit code
   (`echo $?` / `echo %ERRORLEVEL%`).
4. If it is a threading issue, whether the viewport was rendering at the time.

For anything that looks like a security bypass, please use a private advisory
rather than a public issue — see [docs/security.md](docs/security.md).

## License

By contributing you agree your work is released under the MIT license.
