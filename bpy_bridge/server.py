# -*- coding: utf-8 -*-
"""In-Blender remote control server for bpy-bridge.

This module is standalone on purpose. Copy this one file into Blender, exec()
it, and you have a working bridge. At import time it uses nothing outside the
Python standard library and touches ``bpy`` only lazily, so the same file is
importable -- and testable -- outside Blender.

Boot it from Blender's Python console (Shift+F4)::

    exec(compile(open(r"C:\\path\\to\\server.py", encoding="utf-8").read(),
                 "bpy_bridge_server", "exec"))

or from a startup script in ``scripts/startup/`` so every Blender launch is
already listening.
"""

import ast
import io
import json
import os
import queue
import secrets
import socket
import socketserver
import sys
import threading
import time
import traceback

PROTOCOL_VERSION = 1

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
DEFAULT_TIMEOUT = 600.0
MAX_FRAME_BYTES = 4 * 1024 * 1024

OP_EXEC = "exec"
OP_PING = "ping"
OP_STATUS = "status"
OPERATIONS = (OP_EXEC, OP_PING, OP_STATUS)

KIND_OK = "ok"
KIND_AUTH = "auth"
KIND_TIMEOUT = "timeout"
KIND_EXEC = "exec"
KIND_PROTOCOL = "protocol"
KIND_INTERNAL = "internal"

#: Blender renders timers about this often; draining a few jobs per tick keeps
#: the UI responsive while a queued batch still finishes quickly.
_PUMP_INTERVAL = 0.02
_PUMP_BATCH = 8

_LOOPBACK_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")


# --------------------------------------------------------------------- tokens
def default_token_path():
    """Where the shared token lives. Override with ``BPY_BRIDGE_HOME``."""
    home = os.environ.get("BPY_BRIDGE_HOME")
    if not home:
        home = os.path.join(os.path.expanduser("~"), ".bpy-bridge")
    return os.path.join(home, "token")


def read_token(path=None):
    """Return the stored token, or ``None`` when the file is absent or blank."""
    path = path or default_token_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
    except (OSError, IOError):
        return None
    return token or None


def write_token(token, path=None):
    """Persist a token with owner-only permissions where the OS supports it."""
    path = path or default_token_path()
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    try:
        # POSIX honours this; on Windows chmod only toggles the read-only bit,
        # so the real protection there is that the file lives in the user
        # profile. See docs/security.md.
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def ensure_token(token=None, token_path=None, persist=True):
    """Return ``(token, path)``, generating and persisting one if needed.

    An explicitly supplied *token* is written to disk too. That is not
    redundant: the client finds the token by reading this file, so a server
    started with ``BridgeServer(token="...")`` that did not persist it would be
    unreachable to every client using the documented workflow -- the client
    would read a stale token, or none, and fail authentication against a bridge
    that is running perfectly well.

    Pass ``persist=False`` to keep an explicit token out of the filesystem
    entirely, at the cost of having to pass it to the client explicitly as well.
    """
    path = token_path or default_token_path()
    if token:
        if persist:
            write_token(token, path)
        return token, path
    existing = read_token(path)
    if existing:
        return existing, path
    generated = secrets.token_urlsafe(32)
    write_token(generated, path)
    return generated, path


def is_loopback(host):
    """True when *host* only ever resolves to this machine."""
    if host in _LOOPBACK_NAMES:
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname we cannot classify: assume it is reachable from elsewhere.
        return False


# --------------------------------------------------------------------- helper
class BridgeHelper(object):
    """Convenience API injected into the exec namespace as ``bridge``.

    Inside Blender::

        bridge.status()                  # scene / version / camera
        bridge.shot("C:/tmp/ui.png")     # screenshot the Blender window
        bridge.exec_file("C:/tmp/do.py") # run a file in the persistent namespace
        bridge.bpy                       # the real bpy module
    """

    def __init__(self, bpy_module=None):
        self._bpy = bpy_module
        self._namespace = None

    # -- lazy bpy ---------------------------------------------------------
    @property
    def bpy(self):
        if self._bpy is None:
            import bpy as _bpy

            self._bpy = _bpy
        return self._bpy

    def _bind(self, namespace):
        self._namespace = namespace
        return self

    # -- helpers ----------------------------------------------------------
    def status(self):
        """Return a small dict describing the current Blender session."""
        info = {
            "protocol": PROTOCOL_VERSION,
            "pid": os.getpid(),
            "python": sys.version.split()[0],
        }
        bpy = self.bpy
        try:
            info["blender"] = bpy.app.version_string
        except AttributeError:
            info["blender"] = None
        try:
            info["file"] = bpy.data.filepath or None
        except AttributeError:
            info["file"] = None
        try:
            scene = bpy.context.scene
            info["scene"] = scene.name
            info["engine"] = scene.render.engine
            info["objects"] = len(scene.objects)
            info["camera"] = scene.camera.name if scene.camera else None
        except AttributeError:
            pass
        try:
            info["collections"] = [collection.name for collection in bpy.data.collections]
        except AttributeError:
            pass
        return info

    def shot(self, path):
        """Screenshot the Blender window to *path*.

        Uses ``temp_override`` when available (Blender 3.2+) and falls back to
        a bare operator call on older builds.
        """
        bpy = self.bpy
        window_manager = bpy.context.window_manager
        windows = getattr(window_manager, "windows", None) or []
        if not windows:
            raise RuntimeError("no Blender window to screenshot")
        window = windows[0]
        path = os.path.abspath(path)
        try:
            override = bpy.context.temp_override(window=window, screen=window.screen)
        except AttributeError:
            bpy.ops.screen.screenshot(filepath=path)
        else:
            with override:
                bpy.ops.screen.screenshot(filepath=path)
        return path

    def exec_file(self, path):
        """Execute a Python file in the bridge's persistent namespace."""
        path = os.path.normpath(os.path.abspath(path))
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        namespace = self._namespace if self._namespace is not None else {"bridge": self}
        exec(compile(source, path, "exec"), namespace)
        return path


# --------------------------------------------------------------------- server
class BridgeServer(object):
    """A loopback TCP server that runs arbitrary code on Blender's main thread.

    Blender's API is not thread safe, so socket worker threads never touch
    ``bpy``. They enqueue work; a ``bpy.app.timers`` callback drains the queue
    on the main thread and hands the result back. That single design decision
    is what makes the whole thing stable.
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, token=None,
                 token_path=None, bpy_module=None, allow_remote=False,
                 max_frame_bytes=MAX_FRAME_BYTES, namespace=None,
                 persist_token=True):
        if not is_loopback(host) and not allow_remote:
            raise ValueError(
                "refusing to bind %r: it is not a loopback address. "
                "Pass allow_remote=True if you really mean to expose remote "
                "code execution to the network." % (host,)
            )
        self.host = host
        self.port = int(port)
        self.max_frame_bytes = int(max_frame_bytes)
        self.allow_remote = bool(allow_remote)

        self.token, self.token_path = ensure_token(token, token_path,
                                                   persist=persist_token)

        self._bpy = bpy_module
        self._namespace = namespace if namespace is not None else {}
        self._helper = BridgeHelper(bpy_module)
        self._namespace.setdefault("__name__", "__bpy_bridge__")
        self._namespace["bridge"] = self._helper._bind(self._namespace)

        self._queue = queue.Queue()
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        #: Guards the request counter only. Deliberately *not* ``_lock``:
        #: ``stop()`` must never hold a lock that an in-flight handler needs,
        #: or shutdown deadlocks against the threads it is joining.
        self._stats_lock = threading.Lock()
        self._running = False
        self._timer_registered = False
        self._started_at = None
        self._requests = 0

    # -- lifecycle --------------------------------------------------------
    @property
    def bpy(self):
        if self._bpy is None:
            import bpy as _bpy

            self._bpy = _bpy
        return self._bpy

    @property
    def address(self):
        return (self.host, self.port)

    @property
    def running(self):
        return self._running

    @property
    def requests_served(self):
        return self._requests

    def start(self):
        """Bind, start the worker thread, and register the main-thread pump."""
        with self._lock:
            if self._running:
                return self
            self._server = _make_tcp_server((self.host, self.port), self)
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="bpy-bridge",
                daemon=True,
            )
            self._thread.start()
            self._started_at = time.time()
            self._running = True
            self._register_timer()
        return self

    def stop(self):
        """Stop listening and unregister the pump. Safe to call twice.

        The socket is torn down *outside* ``_lock`` on purpose. ``server_close``
        joins the handler threads, and a handler may be mid-request waiting for
        something; holding the lifecycle lock here would turn a slow request
        into a permanent hang.
        """
        with self._lock:
            if not self._running:
                return self
            self._running = False
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        self._unregister_timer()
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=2.0)
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc_info):
        self.stop()
        return False

    # -- timers -----------------------------------------------------------
    def _register_timer(self):
        try:
            timers = self.bpy.app.timers
        except AttributeError:
            # Outside Blender (tests, tooling): the pump is driven manually.
            return
        try:
            timers.register(self._pump, first_interval=_PUMP_INTERVAL, persistent=True)
            self._timer_registered = True
        except Exception:
            traceback.print_exc()

    def _unregister_timer(self):
        if not self._timer_registered:
            return
        self._timer_registered = False
        try:
            self.bpy.app.timers.unregister(self._pump)
        except Exception:
            pass

    # -- main-thread pump -------------------------------------------------
    def _pump(self):
        """Drain queued jobs on Blender's main thread. Called by a timer."""
        for _ in range(_PUMP_BATCH):
            try:
                job, box, done = self._queue.get_nowait()
            except queue.Empty:
                break
            if callable(job):
                self._execute_callable(job, box)
            else:
                self._execute(job, box)
            done.set()
        return _PUMP_INTERVAL

    def _execute_callable(self, fn, box):
        """Run *fn* on the main thread and fill *box*.

        Used for anything that has to touch ``bpy`` -- ``status`` above all.
        Routing it through the queue is the difference between a bridge that is
        merely thread unsafe and one that is correct.
        """
        started = time.time()
        try:
            box["result"] = fn()
            box["ok"] = True
        except BaseException:
            box["ok"] = False
            box["error"] = traceback.format_exc()
        finally:
            box["stdout"] = ""
            box["duration_ms"] = (time.time() - started) * 1000.0

    def _execute(self, code, box):
        """Evaluate *code* in the persistent namespace and fill *box*.

        Semantics match a Python REPL rather than plain ``exec``: if the last
        statement is an expression, its value is evaluated and returned as a
        ``repr``. So ``print("hi"); 6 * 7`` yields ``stdout="hi"`` *and*
        ``result="42"``.

        The earlier implementation compiled the whole snippet as an expression
        and fell back to ``exec`` on ``SyntaxError``. That silently dropped the
        trailing value for every multi-statement snippet, which is exactly the
        shape of code people send interactively -- hence the AST-based split.
        """
        namespace = self._namespace
        out = io.StringIO()
        saved_stdout, saved_stderr = sys.stdout, sys.stderr
        started = time.time()
        sys.stdout = out
        sys.stderr = out
        try:
            tree = ast.parse(code, "<bpy-bridge>", "exec")
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                # Everything before the final expression runs as statements,
                # then the final expression is evaluated for its value.
                trailing = ast.Expression(tree.body[-1].value)
                body = ast.Module(body=tree.body[:-1], type_ignores=[])
                exec(compile(body, "<bpy-bridge>", "exec"), namespace)
                box["result"] = repr(eval(compile(trailing, "<bpy-bridge>", "eval"), namespace))
            else:
                exec(compile(tree, "<bpy-bridge>", "exec"), namespace)
                box["result"] = None
            box["ok"] = True
        except BaseException:
            box["ok"] = False
            box["error"] = traceback.format_exc()
        finally:
            sys.stdout, sys.stderr = saved_stdout, saved_stderr
            box["stdout"] = out.getvalue()
            box["duration_ms"] = (time.time() - started) * 1000.0

    # -- request handling -------------------------------------------------
    def submit(self, job, timeout=DEFAULT_TIMEOUT):
        """Queue *job* for the main thread and block until it finishes.

        *job* is either Python source (``str``) or a zero-argument callable.
        Returns the result box. Raises ``TimeoutError`` if the main thread does
        not pick the job up in time -- note that the job keeps running; there
        is no safe way to interrupt a Python frame.
        """
        box = {}
        done = threading.Event()
        self._queue.put((job, box, done))
        if not done.wait(timeout):
            raise TimeoutError("no result after %ss" % timeout)
        return box

    def handle_frame(self, raw):
        """Turn one raw request frame into one raw response frame.

        Pure function of ``(raw, server state)`` -- no socket involved -- which
        makes it the natural unit to test.
        """
        request_id = None
        started = time.time()
        try:
            request = self._decode(raw)
        except ValueError as exc:
            return self._respond(kind=KIND_PROTOCOL, error=str(exc), started=started)
        request_id = request.get("request_id")
        if not self._token_matches(request.get("token", "")):
            return self._respond(kind=KIND_AUTH, error="bad token", started=started,
                                 request_id=request_id)

        op = request["op"]
        if op == OP_PING:
            return self._respond(result="pong", started=started, request_id=request_id)
        if op == OP_STATUS:
            # Must go through the queue: this runs on a socket thread and
            # ``status()`` reads bpy.context.scene, which is main-thread only.
            try:
                box = self.submit(self._helper.status, request["timeout"])
            except TimeoutError as exc:
                return self._respond(kind=KIND_TIMEOUT, error=str(exc), started=started,
                                     request_id=request_id)
            except Exception:
                return self._respond(kind=KIND_INTERNAL, error=traceback.format_exc(),
                                     started=started, request_id=request_id)
            if not box.get("ok"):
                return self._respond(kind=KIND_INTERNAL, error=box.get("error", ""),
                                     started=started, request_id=request_id)
            return self._respond(result=json.dumps(box.get("result"), ensure_ascii=False),
                                 started=started, request_id=request_id,
                                 duration_ms=box.get("duration_ms"))

        try:
            box = self.submit(request["code"], request["timeout"])
        except TimeoutError as exc:
            return self._respond(kind=KIND_TIMEOUT, error=str(exc), started=started,
                                 request_id=request_id)
        except Exception:
            return self._respond(kind=KIND_INTERNAL, error=traceback.format_exc(),
                                 started=started, request_id=request_id)

        if box.get("ok"):
            return self._respond(result=box.get("result"), stdout=box.get("stdout", ""),
                                 started=started, request_id=request_id,
                                 duration_ms=box.get("duration_ms"))
        return self._respond(kind=KIND_EXEC, error=box.get("error", "unknown error"),
                             stdout=box.get("stdout", ""), started=started,
                             request_id=request_id, duration_ms=box.get("duration_ms"))

    def _token_matches(self, candidate):
        """Constant-time token comparison.

        ``secrets.compare_digest`` needs two byte strings or two ASCII-only
        strings; a token file could in principle contain anything, so encode
        both sides defensively rather than letting a non-ASCII token crash the
        auth path.
        """
        expected = self.token.encode("utf-8")
        try:
            provided = (candidate or "").encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            return False
        return secrets.compare_digest(provided, expected)

    @staticmethod
    def _decode(raw):
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("request is not valid UTF-8: %s" % exc)
        try:
            request = json.loads(raw)
        except ValueError as exc:
            raise ValueError("request is not valid JSON: %s" % exc)
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        op = request.get("op", OP_EXEC)
        if op not in OPERATIONS:
            raise ValueError("unknown op: %r" % (op,))
        request["op"] = op
        request["code"] = request.get("code") or ""
        if not isinstance(request["code"], str):
            raise ValueError("code must be a string")
        request["token"] = request.get("token") or ""
        try:
            timeout = float(request.get("timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        request["timeout"] = timeout if timeout > 0 else DEFAULT_TIMEOUT
        return request

    def _respond(self, kind=KIND_OK, result=None, stdout="", error="",
                 started=None, duration_ms=None, request_id=None):
        if duration_ms is None:
            duration_ms = (time.time() - (started or time.time())) * 1000.0
        response = {
            "protocol": PROTOCOL_VERSION,
            "ok": kind == KIND_OK,
            "kind": kind,
            "result": result,
            "stdout": stdout or "",
            "error": error or "",
            "duration_ms": round(float(duration_ms), 3),
        }
        if request_id is not None:
            response["request_id"] = str(request_id)
        return (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")

    # -- introspection ----------------------------------------------------
    def info(self):
        return {
            "host": self.host,
            "port": self.port,
            "running": self._running,
            "token_path": self.token_path,
            "requests": self._requests,
            "uptime_s": round(time.time() - self._started_at, 2) if self._started_at else 0.0,
        }


class _Handler(socketserver.StreamRequestHandler):
    """One connection, one request, one response. Then close."""

    def handle(self):
        bridge = self.server.bridge
        try:
            raw = self.rfile.readline(bridge.max_frame_bytes + 1)
        except OSError:
            return
        if not raw:
            return
        if len(raw) > bridge.max_frame_bytes or not raw.endswith(b"\n"):
            payload = bridge._respond(kind=KIND_PROTOCOL,
                                      error="frame exceeds %d bytes or is not newline "
                                            "terminated" % bridge.max_frame_bytes)
        else:
            with bridge._stats_lock:
                bridge._requests += 1
            payload = bridge.handle_frame(raw)
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except OSError:
            pass


def _make_tcp_server(address, bridge):
    server = socketserver.ThreadingTCPServer(address, _Handler, bind_and_activate=False)
    server.allow_reuse_address = True
    server.daemon_threads = True
    server.request_queue_size = 32
    server.bridge = bridge
    server.server_bind()
    server.server_activate()
    return server


# ------------------------------------------------------------------- facade
_ACTIVE = None


def start(host=DEFAULT_HOST, port=DEFAULT_PORT, token=None, token_path=None,
          bpy_module=None, allow_remote=False, verbose=True):
    """Start (or return the already running) bridge inside Blender."""
    global _ACTIVE
    if _ACTIVE is not None and _ACTIVE.running:
        if verbose:
            print("[bpy-bridge] already listening on %s:%d" % _ACTIVE.address)
        return _ACTIVE
    server = BridgeServer(host=host, port=port, token=token, token_path=token_path,
                          bpy_module=bpy_module, allow_remote=allow_remote)
    server.start()
    _ACTIVE = server
    if verbose:
        print("[bpy-bridge] listening on %s:%d (protocol v%d)" % (server.host, server.port, PROTOCOL_VERSION))
        print("[bpy-bridge] token file: %s" % server.token_path)
    return server


def stop():
    """Stop the active bridge, if any."""
    global _ACTIVE
    if _ACTIVE is not None:
        _ACTIVE.stop()
        _ACTIVE = None


def active():
    """Return the running bridge, or ``None``."""
    return _ACTIVE if _ACTIVE is not None and _ACTIVE.running else None


if __name__ == "__main__":
    # Importing this file outside Blender should not explode; running it as a
    # script without bpy is a user error worth a clear message.
    try:
        start()
    except ImportError:
        raise SystemExit("bpy-bridge's server must run inside Blender (no bpy module found).")
