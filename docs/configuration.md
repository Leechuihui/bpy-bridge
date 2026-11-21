# Configuration reference

**English** | [简体中文](configuration.zh-CN.md)

Every knob bpy-bridge exposes, with the default and what changing it actually
does. If a setting is not listed here, it does not exist — this page is checked
against the source, not written from memory.

- [Defaults at a glance](#defaults-at-a-glance)
- [Starting the server](#starting-the-server)
- [The token](#the-token)
- [Network settings](#network-settings)
- [Limits and timeouts](#limits-and-timeouts)
- [CLI reference](#cli-reference)
- [Python client reference](#python-client-reference)
- [Exit codes](#exit-codes)
- [Autostart](#autostart)
- [Troubleshooting by symptom](#troubleshooting-by-symptom)

---

## Defaults at a glance

| Setting | Default | Where it lives |
|---|---|---|
| Bind host | `127.0.0.1` | `DEFAULT_HOST` |
| Port | `9876` | `DEFAULT_PORT` |
| Token | random 256-bit, generated on first start | `~/.bpy-bridge/token` |
| Token home override | *(unset)* | `BPY_BRIDGE_HOME` env var |
| Request timeout | `600.0` s | `DEFAULT_TIMEOUT` |
| Max frame size | 4 MiB (`4194304` bytes) | `MAX_FRAME_BYTES` |
| Protocol version | `1` | `PROTOCOL_VERSION` |
| Main-thread pump interval | `0.02` s | `_PUMP_INTERVAL` |
| Jobs drained per pump tick | `8` | `_PUMP_BATCH` |

These are the values you get with no configuration at all. Every one is
overridable; nothing requires a config file.

---

## Starting the server

### From Blender's Python console

The shortest path. `Shift+F4`, then:

```python
exec(compile(open(r"/path/to/server.py", encoding="utf-8").read(),
             "bpy_bridge_server", "exec"))
```

This calls `start()` with all defaults. The server lives until Blender exits, or
until you call `stop()`.

### From Python, with options

When `server.py` is importable as a module (for example, injected as part of a
startup script):

```python
from bpy_bridge import server

server.start(
    port=9876,
    verbose=True,
)
```

`start()` returns the running `BridgeServer` instance. Calling it again while a
server is running returns the **same** instance rather than raising — safe to
call from a script that might run twice.

### From Python, with full control

`BridgeServer` is the real class; `start()` is a thin convenience wrapper.

```python
from bpy_bridge.server import BridgeServer

bridge = BridgeServer(
    host="127.0.0.1",
    port=9876,
    token_path=None,          # None -> ~/.bpy-bridge/token
    allow_remote=False,       # must be True to bind a non-loopback host
    max_frame_bytes=4 * 1024 * 1024,
    persist_token=True,       # False keeps the token out of the filesystem
    namespace=None,           # None -> a fresh persistent namespace
)

bridge.start()      # binds, starts the worker thread, registers the pump
print(bridge.address)
print(bridge.info())

# ... later
bridge.stop()       # safe to call twice
```

Using it as a context manager stops it on the way out:

```python
with BridgeServer(port=9877) as bridge:
    print(bridge.address)
```

### Parameters

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `host` | `str` | `"127.0.0.1"` | Interface to bind. A non-loopback value raises `ValueError` unless `allow_remote=True`. |
| `port` | `int` | `9876` | TCP port. `0` picks a free port; read the real one from `bridge.port` afterwards. |
| `token` | `str` | `None` | Explicit shared secret. `None` generates or reuses one. |
| `token_path` | `str` | `None` | Where the token file lives. `None` uses `~/.bpy-bridge/token`. |
| `bpy_module` | module | `None` | The `bpy` module. `None` imports it lazily — this is what makes the server testable outside Blender. |
| `allow_remote` | `bool` | `False` | Permit binding a non-loopback address. |
| `max_frame_bytes` | `int` | `4194304` | Hard cap on a single request or response frame. |
| `namespace` | `dict` | `None` | Exec namespace. `None` creates a fresh one; pass a dict to share state with an existing script. |
| `persist_token` | `bool` | `True` | Write the token to disk. `False` keeps it in memory only. |

> **`persist_token=False` has a consequence.** Clients find the token by reading
> the file. If you keep it in memory, every client must be given the token
> explicitly (`--token` or `BridgeClient(token=...)`). That is a legitimate
> choice for a throwaway session, and a trap for everything else.

---

## The token

### Where it lives

```
~/.bpy-bridge/token
```

Override the directory with an environment variable:

```bash
export BPY_BRIDGE_HOME=/run/user/1000/bpy-bridge     # POSIX
$env:BPY_BRIDGE_HOME = "C:\Users\you\bpy-bridge"     # PowerShell
```

The file contains the token plus a trailing newline. Whitespace is stripped on
read, so hand-editing it is safe.

### How it is generated

`secrets.token_urlsafe(32)` — 256 bits from the OS CSPRNG, rendered as 43
URL-safe characters. Generated **once**, on first start, then reused.

On POSIX the file is written with mode `0600`. On Windows `chmod` only toggles
the read-only bit, so the real protection is that the file sits inside the user
profile, which is ACL-restricted by default. See [security.md](security.md).

### Inspecting and rotating

```bash
bpy-bridge token-path        # where the client looks
bpy-bridge token             # print the token itself
```

To rotate: delete the file, restart the bridge. The next start generates a fresh
token; clients read the file on every construction, so they pick it up with no
configuration change.

```bash
rm ~/.bpy-bridge/token        # POSIX
Remove-Item ~/.bpy-bridge/token   # PowerShell
```

### Why an explicit token still gets written to disk

If you pass `token="..."`, it is **persisted** by default. This is deliberate:
the client discovers the token through that file, so a server started with an
explicit token that was kept in memory would be unreachable to every client
following the documented workflow. Pass `persist_token=False` to opt out.

---

## Network settings

### Port

```python
server.start(port=9999)
```

```bash
bpy-bridge --port 9999 ping
```

Ports below 1024 need elevated privileges on POSIX. Pick a free port instead;
`9876` is the default and the examples assume it.

If the port is already in use, `start()` raises `OSError` (`EADDRINUSE`). Check
what holds it:

```bash
netstat -ano | findstr 9876      # Windows
lsof -i :9876                    # POSIX
```

### Binding a non-loopback address

You almost certainly should not. The server executes arbitrary Python with your
privileges.

```python
# Raises ValueError unless you mean it:
server.start(host="0.0.0.0", allow_remote=True)
```

The `allow_remote=True` requirement exists so that the decision is visible in
code review rather than hidden in a config value. The CLI warns on stderr
whenever `--host` is not loopback:

```
bpy-bridge: warning: 10.0.0.5 is not a loopback address; the code you send runs
with your user's privileges on that host.
```

`is_loopback()` accepts `127.0.0.0/8`, `::1`, and the usual `localhost` aliases.
A hostname it cannot classify is treated as **not** loopback, so the failure mode
is "refuses to start" rather than "silently exposed".

---

## Limits and timeouts

### Request timeout

Every request carries a budget. The server waits that long for the main thread
to pick the job up, then answers `kind: "timeout"`.

| Layer | Default | How to change |
|---|---|---|
| Client socket read | request timeout + 30 s | automatic |
| Per-request budget | `600` s | `--timeout` / `BridgeClient(timeout=...)` / per call |
| Server fallback | `600` s | `DEFAULT_TIMEOUT` |

```bash
bpy-bridge exec --file build_scene.py --timeout 1800
```

```python
bridge.exec("long_job()", timeout=1800)
```

> **A timeout does not cancel anything.** Python cannot safely interrupt a
> running frame, so the job keeps running on Blender's main thread. The timeout
> stops *you* waiting, not the work. This is stated plainly because it is the one
> limit people assume works differently.

### Frame size

Requests and responses are capped at 4 MiB. Without a cap, a `while True: print(...)`
inside Blender fills the socket buffer and both ends block forever. With it, the
server answers `kind: "protocol"` and closes.

Raise it if you legitimately need to ship large output back:

```python
server.start(max_frame_bytes=16 * 1024 * 1024)
```

Be aware that a large cap on a slow loopback connection means a long stall, not
a fast transfer.

### Pump throughput

The main-thread pump drains up to `_PUMP_BATCH` (8) queued jobs per tick, every
`_PUMP_INTERVAL` (0.02 s). That is a deliberate compromise: draining the queue
in one tick would starve the UI, and one job per tick would make a batch crawl.
These are module constants, not constructor arguments — patch them only if you
have measured a problem:

```python
import bpy_bridge.server as server_module
server_module._PUMP_BATCH = 16
```

---

## CLI reference

```
bpy-bridge [global options] <command> [command options]
```

Global options are accepted **before or after** the command verb:

```bash
bpy-bridge --port 9999 ping      # equivalent
bpy-bridge ping --port 9999
```

### Global options

| Option | Default | Meaning |
|---|---|---|
| `--host HOST` | `127.0.0.1` | Bridge host. |
| `--port PORT` | `9876` | Bridge port. |
| `--token TOKEN` | from token file | Shared secret, inline. |
| `--token-file PATH` | `~/.bpy-bridge/token` | Token file to read. |
| `--timeout SECONDS` | `600` | Per-request budget. |
| `--json` | off | Emit exactly one JSON object on stdout. |
| `--version` | — | Print version and protocol, exit `0`. |

### Commands

| Command | What it does |
|---|---|
| `ping` | Check that Blender is listening and the token is valid. Prints `pong  host:port`. |
| `status` | Print scene, version, camera, object count, and a collection preview. |
| `exec [CODE]` | Evaluate `CODE` inside Blender. |
| `exec --file PATH` | Execute a local `.py` file inside Blender. |
| `shot PATH` | Screenshot the Blender window to `PATH`. Requires a GUI session. |
| `token-path` | Print where the client looks for the token. |
| `token` | Print the token itself. |

### `exec` options

| Option | Meaning |
|---|---|
| `--file PATH`, `-f PATH` | Run a local file instead of inline code. Mutually exclusive with inline code. |
| `--quiet`, `-q` | Suppress stdout and the result; print only errors. |

### `--json` envelope

Success:

```json
{"ok": true, "kind": "ok", "result": "5757", "stdout": "", "error": "", "duration_ms": 0.27, "source": "<argv>"}
```

Failure:

```json
{"ok": false, "kind": "error", "error": "cannot reach Blender bridge ...", "exit": 3}
```

`kind` is the machine-readable outcome. Branch on it; never on `error` text.

### Reading structured data

`result` is the `repr` of the trailing expression, which is **not** parseable
JSON. For machine consumption, `print` JSON and read `stdout`:

```python
# in the script
print(json.dumps(payload))
```

```bash
bpy-bridge exec --file report.py --json | python -c "import json,sys; print(json.load(sys.stdin)['stdout'])"
```

---

## Python client reference

```python
from bpy_bridge import BridgeClient

bridge = BridgeClient(
    host="127.0.0.1",
    port=9876,
    token=None,          # None -> read from token file
    token_path=None,     # None -> ~/.bpy-bridge/token
    timeout=600.0,
)
```

Creating a client is cheap and side-effect free; nothing connects until the first
call. Connections are not pooled — one request per connection, matching the
server.

| Method | Returns | Notes |
|---|---|---|
| `ping()` | `True` | Raises `BridgeAuthError` on a bad token. |
| `status()` | `dict` | Uses the dedicated `status` op, so the payload is real JSON. |
| `exec(code, timeout=None)` | `ExecResult` | Never raises for a remote exception; inspect `ok`/`kind`. |
| `exec_or_raise(code, timeout=None)` | `str` | Raises on failure. Use in batches. |
| `run_file(path, timeout=None)` | `ExecResult` | Executes a local `.py` inside Blender. |
| `screenshot(path, timeout=None)` | `ExecResult` | Blender screenshots its own window. |
| `BridgeClient.from_token_file(path)` | `BridgeClient` | Convenience constructor. |

`ExecResult` carries `ok`, `kind`, `result`, `stdout`, `error`, `duration_ms`,
and `request_id`. It is falsy when `ok` is `False`, and
`result.raise_for_status()` throws the matching exception subclass.

```python
result = bridge.exec("1 / 0")
print(result.ok)      # False
print(result.kind)    # 'exec'
print(result.error)   # the real traceback, rendered inside Blender
```

---

## Exit codes

| Code | Meaning | Typical cause |
|---|---|---|
| `0` | Success | — |
| `1` | Code ran inside Blender and raised | Your script has a bug |
| `2` | Usage error | Bad flags, unreadable `--file`, no code given |
| `3` | Cannot reach Blender | Not running, wrong port, bridge not started |
| `4` | Token rejected | Client and server read different token files |
| `5` | Timed out | Job not picked up within the budget |

`--json` failures also carry `"exit": <code>`, so a caller never branches on
stderr text.

---

## Autostart

Blender runs every `.py` in its `scripts/startup/` directory at launch. Put this
there and the bridge is always available:

```python
# bpy_bridge_startup.py
import os
import traceback

SERVER = os.path.expanduser("~/tools/bpy-bridge/bpy_bridge/server.py")

try:
    with open(SERVER, "r", encoding="utf-8") as handle:
        source = handle.read()
    exec(compile(source, SERVER, "exec"), {"__name__": "__bpy_bridge_startup__"})
except Exception:
    # Never let the bridge break Blender's startup: an exception here leaves
    # Blender half-initialised.
    traceback.print_exc()
    print("[bpy-bridge] autostart failed; continuing without the bridge")
```

Config directory per OS:

| OS | Path |
|---|---|
| Linux | `~/.config/blender/<version>/scripts/startup/` |
| macOS | `~/Library/Application Support/Blender/<version>/scripts/startup/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\<version>\scripts\startup\` |

To use a different port at startup, call `start()` explicitly instead of relying
on the file's `__main__` block:

```python
exec(compile(source, SERVER, "exec"), namespace)
namespace["start"](port=9999)
```

---

## Troubleshooting by symptom

### `cannot reach Blender bridge` (exit 3)

In order of likelihood:

1. The bridge is not running in *this* Blender instance. Start it in the console.
2. Blender runs as a different user, so it wrote its token to a different home.
3. Another process owns the port — check with `netstat`/`lsof`.
4. A firewall blocks loopback (rare, but happens on locked-down machines).

### `bad token` (exit 4)

Client and server disagree about the token file. Compare:

```bash
bpy-bridge token-path        # what the client reads
```

with the `token file:` line Blender printed at startup. A mismatch usually means
different users or a `BPY_BRIDGE_HOME` set for only one side.

### `timeout` (exit 5)

The main thread never picked the job up. Usual causes:

- Blender is busy with something modal (a file dialog blocks the timer).
- A previous job is still running and holding the main thread.
- The bridge was started but `bpy.app.timers` is not firing — check that Blender
  is not in a state that suspends timers.

### `NameError` or `AttributeError` in your code

Your script, not the bridge. The traceback is the real one from inside Blender,
so the line numbers are trustworthy. Variables persist between requests; a stale
name from an earlier request is a common surprise:

```bash
bpy-bridge exec "count"    # works if a previous request assigned it
```

### Output is huge or truncated

The frame cap is 4 MiB. Either reduce what you print or raise
`max_frame_bytes`. Note that exceeding the cap yields `kind: "protocol"`, not a
truncated result — the response is refused rather than silently cut.
