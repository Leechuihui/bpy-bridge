# Security model

`bpy-bridge` runs arbitrary Python inside your Blender, with your user's
privileges, on your machine. That is the entire feature. Everything below is
about making sure it does that *only* for you.

## Threat model

**In scope.** Another process on the same machine — or a browser page via a
local-network request — reaching the bridge without authorization and executing
code as your user. This is the realistic risk, and the defaults are built around
it.

**Out of scope.** An attacker who can already read your token file, run code as
your user, or attach a debugger. At that point the bridge is not your problem.

## Controls

### Bind address

The server binds `127.0.0.1` by default. `BridgeServer(host="0.0.0.0")` raises
`ValueError` before a socket is ever created. Binding elsewhere requires the
explicit `allow_remote=True` flag, which exists so that the decision is visible
in code review rather than buried in a config file.

The CLI prints a warning to stderr whenever `--host` is not loopback:

```
bpy-bridge: warning: 10.0.0.5 is not a loopback address; the code you send runs
with your user's privileges on that host.
```

`is_loopback()` classifies by `ipaddress.ip_address(...).is_loopback`, plus the
usual `localhost` aliases. A hostname it cannot resolve is treated as **not**
loopback, so the failure mode is "refuses to start" rather than "silently
exposed".

### Token

- Generated with `secrets.token_urlsafe(32)` — 256 bits from the OS CSPRNG.
- Stored at `~/.bpy-bridge/token` (override with `BPY_BRIDGE_HOME`).
- Written with `chmod 0600` on POSIX. On Windows, `chmod` only toggles the
  read-only bit; the real protection there is that the file lives inside the
  user profile, which is ACL-restricted by default. If you need more, put the
  file somewhere your other users cannot traverse.
- Compared with `secrets.compare_digest`, byte-encoded on both sides so that a
  non-ASCII token cannot raise `TypeError` inside the auth path and accidentally
  fail open. (It wouldn't have failed open — the exception would have produced
  an error response — but a crash in the auth path is still the wrong shape.)
- Never logged, never printed by the CLI except by the explicit `bpy-bridge
  token` subcommand.

Rotate the token by deleting the file and restarting the bridge. Clients read it
from disk on each construction, so they pick up the new value automatically.

### Frame size

Requests and responses are capped at 4 MiB. Without a cap, a `while True:
print(...)` inside Blender fills the socket buffer and both ends wait forever on
each other. With the cap, the server replies `kind: "protocol"` and closes.

### Timeouts

Every request carries a budget. The server blocks on a `threading.Event` with
that timeout and answers `kind: "timeout"` if the main thread never picks the job
up. The client sets its socket read timeout to `request timeout + 30s` so that a
legitimately slow render does not look like a dropped connection.

## What this does not protect against

- **Code you send.** There is no sandbox, no import allowlist, no filesystem
  jail. If you send `import os; os.remove(...)`, it removes. That is the deal.
- **Cancellation.** Python cannot safely interrupt a running frame. A timed-out
  job keeps running on Blender's main thread; the timeout only stops *you*
  waiting.
- **Anyone with your token file.** Reading the file is equivalent to full code
  execution. Treat it like an SSH key.
- **Blender's own add-ons.** Code runs in the same interpreter as every add-on
  you have installed, with whatever globals they left behind.

## Running it on a shared machine

If other users share the host, loopback is not a boundary — any local user can
connect to `127.0.0.1`. The token is the only boundary, so:

1. Confirm the token file's permissions actually exclude other users. On POSIX,
   `ls -l ~/.bpy-bridge/token` should show `-rw-------`.
2. Prefer a per-user `BPY_BRIDGE_HOME` outside any shared directory.
3. Rotate the token after any session where you were not sure.

## Reporting

If you find a way to bypass the loopback check or the token check, please open a
private security advisory on the repository rather than a public issue.
