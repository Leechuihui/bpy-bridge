# -*- coding: utf-8 -*-
"""Wire protocol for bpy-bridge.

The protocol is deliberately boring: one JSON object per line, in each
 direction. That is it. No length prefixes, no binary frames, no handshake
beyond a shared token. It is easy to implement in any language, which is the
whole point -- the server lives inside Blender's Python, the client may be
Node, Go, Rust, or a shell script.

A request looks like::

    {"protocol": 1, "op": "exec", "code": "1 + 1", "token": "...",
     "timeout": 600.0, "request_id": "3f2a"}

A response looks like::

    {"protocol": 1, "ok": true, "kind": "ok", "result": "2",
     "stdout": "", "error": "", "duration_ms": 0.4, "request_id": "3f2a"}

``kind`` is the machine-readable reason, so clients never have to pattern
match on English error strings.
"""

PROTOCOL_VERSION = 1

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876

#: Hard cap on a single frame in either direction. Protects both sides from a
#: runaway ``print()`` loop inside Blender filling the socket buffer forever.
MAX_FRAME_BYTES = 4 * 1024 * 1024

#: Default execution budget in seconds. Long enough for a render, short enough
#: that a client does not hang forever on a dead Blender.
DEFAULT_TIMEOUT = 600.0

#: Operations understood by the server.
OP_EXEC = "exec"
OP_PING = "ping"
OP_STATUS = "status"
OPERATIONS = (OP_EXEC, OP_PING, OP_STATUS)

#: Response ``kind`` values.
KIND_OK = "ok"
KIND_AUTH = "auth"
KIND_TIMEOUT = "timeout"
KIND_EXEC = "exec"
KIND_PROTOCOL = "protocol"
KIND_INTERNAL = "internal"
KINDS = (KIND_OK, KIND_AUTH, KIND_TIMEOUT, KIND_EXEC, KIND_PROTOCOL, KIND_INTERNAL)


class BridgeError(RuntimeError):
    """Base class for every error this package raises."""


class ProtocolError(BridgeError):
    """The peer sent something that does not conform to the protocol."""


class BridgeUnreachable(BridgeError):
    """Nothing is listening, or the connection dropped."""


class BridgeAuthError(BridgeError):
    """The token was rejected."""


class BridgeTimeout(BridgeError):
    """The code did not finish inside the requested budget."""


class RemoteExecError(BridgeError):
    """Code ran inside Blender and raised.

    ``remote_traceback`` holds the traceback rendered inside Blender, where the
    line numbers actually refer to something.
    """

    def __init__(self, message, remote_traceback="", stdout=""):
        super().__init__(message)
        self.remote_traceback = remote_traceback
        self.stdout = stdout


# --------------------------------------------------------------------- helpers

def _as_float(value, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return number


def make_request(code="", token="", timeout=DEFAULT_TIMEOUT, op=OP_EXEC, request_id=None):
    """Build a validated request dict."""
    if op not in OPERATIONS:
        raise ProtocolError("unknown op: %r (expected one of %s)" % (op, ", ".join(OPERATIONS)))
    if not isinstance(code, str):
        raise ProtocolError("code must be a string, got %s" % type(code).__name__)
    request = {
        "protocol": PROTOCOL_VERSION,
        "op": op,
        "code": code,
        "token": token or "",
        "timeout": _as_float(timeout, DEFAULT_TIMEOUT),
    }
    if request_id is not None:
        request["request_id"] = str(request_id)
    return request


def encode_request(**kwargs):
    """Serialise a request to bytes, newline terminated."""
    import json

    return (json.dumps(make_request(**kwargs), ensure_ascii=False) + "\n").encode("utf-8")


def decode_request(raw):
    """Parse and validate one request frame.

    Raises :class:`ProtocolError` on anything that is not a JSON object with a
    usable ``op``.
    """
    import json

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("request is not valid UTF-8: %s" % exc)
    if not raw or not raw.strip():
        raise ProtocolError("empty request frame")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError("request is not valid JSON: %s" % exc)
    if not isinstance(payload, dict):
        raise ProtocolError("request must be a JSON object, got %s" % type(payload).__name__)
    op = payload.get("op", OP_EXEC)
    if op not in OPERATIONS:
        raise ProtocolError("unknown op: %r" % (op,))
    payload["op"] = op
    payload["code"] = payload.get("code") or ""
    if not isinstance(payload["code"], str):
        raise ProtocolError("code must be a string")
    payload["token"] = payload.get("token") or ""
    payload["timeout"] = _as_float(payload.get("timeout"), DEFAULT_TIMEOUT)
    return payload


def make_response(ok=None, kind=KIND_OK, result=None, stdout="", error="",
                  duration_ms=0.0, request_id=None, **extra):
    """Build a validated response dict.

    ``ok`` defaults to ``kind == "ok"`` so the two can never disagree. Pass it
    explicitly only for the rare case where a successful call still wants
    ``ok=False`` -- and if you think you need that, you probably want a new
    ``kind`` instead.
    """
    if kind not in KINDS:
        raise ProtocolError("unknown response kind: %r" % (kind,))
    if ok is None:
        ok = kind == KIND_OK
    response = {
        "protocol": PROTOCOL_VERSION,
        "ok": bool(ok),
        "kind": kind,
        "result": result,
        "stdout": stdout or "",
        "error": error or "",
        "duration_ms": round(float(duration_ms), 3),
    }
    if request_id is not None:
        response["request_id"] = str(request_id)
    response.update(extra)
    return response


def encode_response(**kwargs):
    """Serialise a response to bytes, newline terminated."""
    import json

    return (json.dumps(make_response(**kwargs), ensure_ascii=False) + "\n").encode("utf-8")


def decode_response(raw):
    """Parse a response frame into a dict.

    Tolerant by design: a response missing optional fields is still usable, so
    a hand-written test server does not have to be perfect.
    """
    import json

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("response is not valid UTF-8: %s" % exc)
    if not raw or not raw.strip():
        raise ProtocolError("empty response frame")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError("response is not valid JSON: %s" % exc)
    if not isinstance(payload, dict):
        raise ProtocolError("response must be a JSON object")
    payload.setdefault("ok", False)
    payload.setdefault("kind", KIND_OK if payload["ok"] else KIND_INTERNAL)
    payload.setdefault("result", None)
    payload.setdefault("stdout", "")
    payload.setdefault("error", "")
    payload.setdefault("duration_ms", 0.0)
    return payload
