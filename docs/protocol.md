# Wire protocol, version 1

This document is normative. If you write a client in another language, this is
the whole specification.

## Transport

- TCP over IPv4/IPv6, conventionally `127.0.0.1:9876`.
- One connection carries **exactly one request and one response**, then the
  server closes it.
- Both directions are UTF-8 encoded JSON, one object per line, terminated by
  `\n`. No length prefix, no framing beyond the newline.
- Maximum frame size in either direction: **4 MiB** (`MAX_FRAME_BYTES`).

## Request

```json
{
  "protocol": 1,
  "op": "exec",
  "code": "len(bpy.data.objects)",
  "token": "…",
  "timeout": 600.0,
  "request_id": "3f2a"
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `op` | no | string | `exec` (default), `ping`, or `status`. |
| `code` | for `exec` | string | Python source. Evaluated as an expression first; if that fails with `SyntaxError`, executed as statements. |
| `token` | yes | string | Shared secret. Empty or wrong → `kind: "auth"`. |
| `timeout` | no | number | Seconds the server waits for the main thread. Default `600`. Non-positive or unparseable values fall back to the default. |
| `request_id` | no | string | Echoed back in the response. Use it to correlate. |
| `protocol` | no | integer | Currently `1`. |

`code` may be `""` for `ping` and `status`.

## Response

```json
{
  "protocol": 1,
  "ok": true,
  "kind": "ok",
  "result": "1886",
  "stdout": "",
  "error": "",
  "duration_ms": 0.412,
  "request_id": "3f2a"
}
```

| Field | Type | Notes |
|---|---|---|
| `ok` | boolean | Always `kind == "ok"`. |
| `kind` | string | Machine-readable outcome, see below. |
| `result` | string \| null | For `exec`: the Python `repr()` of the expression's value, or `null` for statement blocks. For `ping`: `"pong"`. For `status`: a JSON *string* that parses to the status object. |
| `stdout` | string | Everything the code wrote to `sys.stdout` or `sys.stderr`, interleaved in write order. |
| `error` | string | Traceback or message. Empty on success. |
| `duration_ms` | number | Wall time spent on the main thread, rounded to 3 decimals. |
| `request_id` | string | Present only if the request supplied one. |

### `kind` values

| `kind` | `ok` | Meaning |
|---|---|---|
| `ok` | true | Success. |
| `auth` | false | Token missing or wrong. The request was not executed. |
| `timeout` | false | The main thread did not pick up the job within `timeout` seconds. **The code may still run.** |
| `exec` | false | The code ran and raised. `error` holds the traceback. |
| `protocol` | false | Malformed request: bad JSON, unknown `op`, oversized frame. |
| `internal` | false | The bridge itself failed (e.g. no main-thread pump). |

Clients should branch on `kind`, never on `error` text.

## `result` is a repr, not JSON

This trips people up, so it is worth stating twice. For `exec`, the server does:

```python
repr(eval(compiled, namespace))
```

so `1 + 1` yields the string `"2"`, `"hi"` yields `"'hi'"` (with quotes), and a
dict yields `"{'a': 1}"` — which is **not** valid JSON. If you need structured
data, return a JSON string yourself:

```python
import json; json.dumps({"objects": len(bpy.data.objects)})
```

and parse it on the client. The `status` op already does this for you.

## Namespace persistence

Each connection gets fresh transport state, but the exec namespace is shared and
persistent for the lifetime of the bridge. Variables you assign stay assigned:

```
exec: "counter = 0"      → result null
exec: "counter += 1"     → result null
exec: "counter"          → result "1"
```

The namespace always contains:

- `__name__` = `"__bpy_bridge__"`
- `bridge` — a helper object (see below)

`bpy` is *not* injected automatically; `import bpy` works because the code runs
inside Blender, but importing it once into the namespace keeps things readable.

## The `bridge` helper

Inside the exec namespace, `bridge` exposes:

| Member | Description |
|---|---|
| `bridge.bpy` | The real `bpy` module. |
| `bridge.status()` | Dict with `blender`, `scene`, `file`, `engine`, `objects`, `camera`, `collections`, `python`, `pid`. |
| `bridge.shot(path)` | Screenshot the Blender window to `path`. Returns the absolute path. |
| `bridge.exec_file(path)` | Execute a local `.py` file in the same persistent namespace. |

## Writing a client

The minimum viable client, in Python, is about twenty lines:

```python
import json, socket

def call(code, token, host="127.0.0.1", port=9876, timeout=600):
    with socket.create_connection((host, port), timeout=timeout + 30) as sock:
        sock.sendall((json.dumps({
            "op": "exec", "code": code, "token": token, "timeout": timeout,
        }) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8"))
```

Remember to set the socket read timeout to at least the request `timeout` plus
slack; otherwise a slow render will look like a dropped connection.

## Versioning

`protocol` is `1`. A future incompatible change bumps it to `2`, and the server
will accept both for at least one minor release. Adding a new `op` is *not*
considered breaking; an unknown `op` already yields `kind: "protocol"`.
