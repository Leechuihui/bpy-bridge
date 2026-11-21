# -*- coding: utf-8 -*-
"""Prove that ``server.py`` works with no package around it.

The README makes a specific promise: copy this one file into Blender, ``exec()``
it, done. That promise is easy to break accidentally -- a stray
``from .protocol import ...`` would still pass the test suite, because the suite
imports the package, but would explode for every user who copied the file.

This script loads ``server.py`` as a standalone module from a temporary directory
that contains nothing else, then starts a real bridge with a fake ``bpy`` and
talks to it over a real socket.

Run directly: ``python tests/standalone_server_check.py``
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import types


def load_standalone(path):
    """Import *path* as a module named ``bpy_bridge_server``."""
    module = types.ModuleType("bpy_bridge_server")
    module.__file__ = path
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    exec(compile(source, path, "exec"), module.__dict__)
    return module


def make_minimal_bpy():
    """The smallest bpy that lets the server's timer registration succeed."""
    class _Timers(object):
        def __init__(self):
            self.registered = []

        def register(self, fn, first_interval=0.0, persistent=False):
            self.registered.append(fn)
            return fn

        def unregister(self, fn):
            pass

    app = types.SimpleNamespace(version_string="4.2.0", timers=_Timers())
    return types.SimpleNamespace(app=app)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    source = os.path.join(os.path.dirname(here), "bpy_bridge", "server.py")
    if not os.path.exists(source):
        print("FAIL: cannot find %s" % source)
        return 1

    # Isolate: copy the single file somewhere with no siblings, so a relative
    # import would fail loudly instead of accidentally resolving.
    temp_dir = tempfile.mkdtemp(prefix="bpy-bridge-standalone-")
    try:
        isolated = os.path.join(temp_dir, "server.py")
        shutil.copyfile(source, isolated)
        module = load_standalone(isolated)

        server = module.BridgeServer(
            host="127.0.0.1",
            port=0,
            token="standalone-check",
            token_path=os.path.join(temp_dir, "token"),
            bpy_module=make_minimal_bpy(),
        )
        server.start()
        try:
            payload = json.dumps({
                "op": "ping", "token": "standalone-check", "protocol": 1,
            }).encode("utf-8") + b"\n"
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
                sock.sendall(payload)
                raw = sock.recv(65536)
            response = json.loads(raw.decode("utf-8"))
            if not response.get("ok"):
                print("FAIL: ping over a standalone server failed: %r" % (response,))
                return 1
            if response.get("result") != "pong":
                print("FAIL: expected pong, got %r" % (response.get("result"),))
                return 1
        finally:
            server.stop()

        print("OK: server.py runs standalone (no package required)")
        return 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
