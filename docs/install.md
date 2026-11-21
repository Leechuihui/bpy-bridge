# Installing the bridge so it is always there

Two ways, depending on how much you want to think about it.

## Option A — the one-liner (no install)

In Blender's Python console (`Shift+F4`):

```python
exec(compile(open(r"/path/to/server.py", encoding="utf-8").read(),
             "bpy_bridge_server", "exec"))
```

This is the recommended path if you are trying the tool out or if you want to
control exactly when the bridge is listening. `server.py` imports nothing outside
the standard library, so a single file is a complete installation.

## Option B — autostart on every Blender launch

Blender runs every `.py` file in its `scripts/startup/` directory at launch. Drop
a small file there and the bridge comes up with Blender.

Find your config directory:

| OS | Path |
|---|---|
| Linux | `~/.config/blender/<version>/scripts/startup/` |
| macOS | `~/Library/Application Support/Blender/<version>/scripts/startup/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\<version>\scripts\startup\` |

Create `bpy_bridge_startup.py` there:

```python
# ~/.config/blender/4.2/scripts/startup/bpy_bridge_startup.py
import os
import traceback

SERVER = os.path.expanduser("~/tools/bpy-bridge/bpy_bridge/server.py")

try:
    with open(SERVER, "r", encoding="utf-8") as handle:
        source = handle.read()
    exec(compile(source, SERVER, "exec"), {"__name__": "__bpy_bridge_startup__"})
except Exception:
    # Never let the bridge break Blender's startup: a broken autostart file
    # that raises here leaves Blender in a half-initialized state.
    traceback.print_exc()
    print("[bpy-bridge] autostart failed; continuing without the bridge")
```

Restart Blender. You should see the `[bpy-bridge] listening on ...` line in the
system console.

> **Note on paths.** `~` is expanded with `os.path.expanduser`, so the same file
> works on all three platforms if you keep the server in a fixed relative
> location. Use a raw string or forward slashes on Windows to avoid `\U`
> escape surprises.

## Verifying

```bash
bpy-bridge ping
```

`pong  127.0.0.1:9876` means everything is wired up.

If it says `cannot reach Blender bridge`, in order of likelihood:

1. The bridge is not running in *this* Blender instance (start it in the console).
2. Blender is running as a different user, so it wrote its token to a different
   home directory.
3. Another process owns port 9876. Check with
   `netstat -ano | findstr 9876` (Windows) or `lsof -i :9876` (POSIX).
4. A firewall is blocking loopback, which should not happen but occasionally
   does on locked-down corporate machines.

If it says `bad token`, the client and server disagree about the token file.
`bpy-bridge token-path` prints the path the client used; compare it with the
`token file:` line the server printed at startup.

## Choosing a port

```python
# in Blender
server = start(port=9999)
```

```bash
bpy-bridge --port 9999 ping
```

Ports below 1024 need elevated privileges on POSIX and are not worth it.

## Uninstalling

Delete the startup file. That is it — nothing else is modified. Optionally delete
`~/.bpy-bridge/` to remove the token.
