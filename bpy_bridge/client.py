# -*- coding: utf-8 -*-
"""Client side of bpy-bridge.

Standard library only, so it works in any Python 3.8+ environment: a venv, a
CI runner, a Blender *other* than the one being controlled, or a phone via
Termux.

    from bpy_bridge import BridgeClient

    with BridgeClient() as bridge:
        print(bridge.ping())
        print(bridge.exec("len(bpy.data.objects)").result)
"""

import json
import socket
import time

from . import protocol
from .protocol import (
    BridgeAuthError,
    BridgeError,
    BridgeTimeout,
    BridgeUnreachable,
    ProtocolError,
    RemoteExecError,
)


class ExecResult(object):
    """The outcome of one ``exec`` call.

    Always returned, even on failure, so callers can choose between inspecting
    ``ok`` and letting :meth:`raise_for_status` throw.
    """

    __slots__ = ("ok", "kind", "result", "stdout", "error", "duration_ms", "request_id")

    def __init__(self, ok=False, kind=protocol.KIND_INTERNAL, result=None, stdout="",
                 error="", duration_ms=0.0, request_id=None):
        self.ok = bool(ok)
        self.kind = kind
        self.result = result
        self.stdout = stdout or ""
        self.error = error or ""
        self.duration_ms = duration_ms or 0.0
        self.request_id = request_id

    def __repr__(self):
        status = "ok" if self.ok else "error(%s)" % self.kind
        return "<ExecResult %s %.1fms>" % (status, self.duration_ms)

    def __bool__(self):
        return self.ok

    def raise_for_status(self):
        """Throw the matching :class:`BridgeError` subclass if this failed."""
        if self.ok:
            return self
        if self.kind == protocol.KIND_AUTH:
            raise BridgeAuthError(self.error or "token rejected")
        if self.kind == protocol.KIND_TIMEOUT:
            raise BridgeTimeout(self.error or "execution timed out")
        if self.kind == protocol.KIND_PROTOCOL:
            raise ProtocolError(self.error or "protocol error")
        if self.kind == protocol.KIND_EXEC:
            raise RemoteExecError(self.error or "remote exception", self.error, self.stdout)
        raise BridgeError(self.error or "unknown bridge error (%s)" % self.kind)

    @classmethod
    def from_response(cls, response):
        return cls(
            ok=response.get("ok", False),
            kind=response.get("kind", protocol.KIND_INTERNAL),
            result=response.get("result"),
            stdout=response.get("stdout", ""),
            error=response.get("error", ""),
            duration_ms=response.get("duration_ms", 0.0),
            request_id=response.get("request_id"),
        )


class BridgeClient(object):
    """One request per connection, matching the server's design.

    Creating a client is cheap and side effect free; nothing connects until the
    first call. Use it as a context manager to reuse a single client, though
    that only saves object allocation -- connections are not pooled.
    """

    def __init__(self, host=protocol.DEFAULT_HOST, port=protocol.DEFAULT_PORT,
                 token=None, token_path=None, timeout=protocol.DEFAULT_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        if token is None:
            from .server import read_token

            token = read_token(token_path)
        self.token = token or ""
        self.last_address = None

    # -- construction helpers ---------------------------------------------
    @classmethod
    def from_token_file(cls, path, host=protocol.DEFAULT_HOST, port=protocol.DEFAULT_PORT,
                        timeout=protocol.DEFAULT_TIMEOUT):
        from .server import read_token

        token = read_token(path)
        if not token:
            raise BridgeAuthError("no token found in %s" % path)
        return cls(host=host, port=port, token=token, timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    # -- transport --------------------------------------------------------
    def _roundtrip(self, **request_kwargs):
        """Send one request, return the decoded response dict."""
        request_kwargs.setdefault("timeout", self.timeout)
        payload = protocol.encode_request(token=self.token, **request_kwargs)
        started = time.time()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise BridgeUnreachable(
                "cannot reach Blender bridge at %s:%d -- is Blender running with the "
                "bridge started? (%s)" % (self.host, self.port, exc)
            )
        self.last_address = sock.getsockname()
        try:
            # The server may legitimately take the whole execution budget, so the
            # socket read timeout must be the request timeout plus slack.
            sock.settimeout(self.timeout + 30.0)
            sock.sendall(payload)
            buffer = b""
            while b"\n" not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > protocol.MAX_FRAME_BYTES:
                    raise ProtocolError("response exceeded %d bytes" % protocol.MAX_FRAME_BYTES)
        except socket.timeout:
            raise BridgeTimeout(
                "no response after %.1fs from %s:%d" % (time.time() - started, self.host, self.port)
            )
        except OSError as exc:
            raise BridgeUnreachable("connection to %s:%d dropped: %s" % (self.host, self.port, exc))
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return protocol.decode_response(buffer)

    # -- public API -------------------------------------------------------
    def ping(self):
        """Return ``True`` when the bridge answers with a valid token."""
        response = self._roundtrip(op=protocol.OP_PING)
        result = ExecResult.from_response(response)
        if not result.ok:
            result.raise_for_status()
        return True

    def status(self):
        """Return the server's self-description as a dict.

        Uses the dedicated ``status`` op rather than evaluating
        ``bridge.status()`` as code: the op returns JSON, whereas an ``exec``
        would return the Python ``repr`` of a dict, which is not parseable.
        """
        result = ExecResult.from_response(self._roundtrip(op=protocol.OP_STATUS))
        if not result.ok:
            result.raise_for_status()
        return self._coerce_dict(result.result)

    def exec(self, code, timeout=None):
        """Evaluate *code* inside Blender, returning an :class:`ExecResult`."""
        if not isinstance(code, str):
            raise TypeError("code must be a str, got %s" % type(code).__name__)
        return ExecResult.from_response(
            self._roundtrip(op=protocol.OP_EXEC, code=code, timeout=timeout or self.timeout)
        )

    def exec_or_raise(self, code, timeout=None):
        """Like :meth:`exec` but raises on failure. Returns the result string."""
        result = self.exec(code, timeout=timeout)
        result.raise_for_status()
        return result.result

    def call(self, code, timeout=None):
        """Alias for :meth:`exec`, kept because ``call`` reads better in scripts."""
        return self.exec(code, timeout=timeout)

    def run_file(self, path, timeout=None):
        """Execute a local ``.py`` file inside Blender via ``bridge.exec_file``."""
        import os

        path = os.path.abspath(path)
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        return self.exec('bridge.exec_file(r"%s")' % escaped, timeout=timeout)

    def screenshot(self, path, timeout=None):
        """Ask Blender to screenshot its own window into *path*."""
        escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
        return self.exec('bridge.shot(r"%s")' % escaped, timeout=timeout)

    def _coerce_dict(self, result):
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except ValueError:
                return {"raw": result}
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        return {"raw": result}

    def __repr__(self):
        return "<BridgeClient %s:%d>" % (self.host, self.port)
