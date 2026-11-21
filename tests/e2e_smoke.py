# -*- coding: utf-8 -*-
"""End-to-end smoke test: a bridge in one process, the CLI in another.

The unit tests exercise each layer in isolation. This script exercises the thing
a user actually does -- start Blender, run `bpy-bridge exec` in a shell -- by
standing a bridge up in a *separate process* with a fake `bpy`, then driving it
through the real installed CLI entry point and checking exit codes.

It is deliberately not part of the pytest suite: it shells out, it needs the
package installed, and it is slow enough that nobody wants it in a fast loop.
CI runs it as a separate step.

Run: python tests/e2e_smoke.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: Decode every child pipe as UTF-8, regardless of the host locale.
#:
#: ``text=True`` alone uses the *locale* encoding, which on a Chinese Windows
#: install is GBK. The CLI emits UTF-8 (its error messages can contain non-ASCII
#: paths, and CI runners are UTF-8), so the two disagree and the reader thread
#: raises ``UnicodeDecodeError``. Worse, that exception is swallowed by
#: ``subprocess``'s reader thread: the process still returns exit 0, the stderr
#: text is silently lost, and a real failure would be reported as a pass. Pinning
#: the encoding on both sides is what makes this script trustworthy.
PIPE_TEXT = dict(text=True, encoding="utf-8", errors="replace")


def child_env(extra=None):
    """Environment for a child process, forced to UTF-8 I/O."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env

# The child process runs this snippet: build a fake bpy, start a real bridge,
# print the port and token path, then idle until killed.
BRIDGE_CHILD = r'''
import json, sys, time, types

sys.path.insert(0, {root!r})
from bpy_bridge.server import BridgeServer


class _Timers(object):
    def __init__(self):
        self.cbs = []

    def register(self, fn, first_interval=0.0, persistent=False):
        self.cbs.append(fn)
        return fn

    def unregister(self, fn):
        pass

    def tick(self):
        for fn in list(self.cbs):
            fn()


class _App(object):
    version_string = "4.2.0"

    def __init__(self):
        self.timers = _Timers()


class _Scene(object):
    name = "SmokeScene"
    objects = [object()] * 5

    class render(object):
        engine = "CYCLES"

    camera = None


class _Ctx(object):
    scene = _Scene()


class _Data(object):
    filepath = "/tmp/smoke.blend"
    collections = []


bpy = types.SimpleNamespace(app=_App(), context=_Ctx(), data=_Data())

server = BridgeServer(
    host="127.0.0.1",
    port=0,
    token="smoke-token",
    token_path={token_path!r},
    bpy_module=bpy,
)
server.start()

# Play Blender's main thread: keep the pump turning so queued jobs run.
print(json.dumps({{"port": server.port, "token": "smoke-token"}}), flush=True)
deadline = time.time() + 120
while time.time() < deadline:
    server._pump()
    time.sleep(0.005)
server.stop()
'''


class SmokeFailure(AssertionError):
    pass


def run_cli(args, env, expect=0):
    """Invoke the CLI as a subprocess and assert on its exit code."""
    command = [sys.executable, "-m", "bpy_bridge.cli"] + args
    completed = subprocess.run(
        command,
        capture_output=True,
        env=env,
        timeout=60,
        cwd=ROOT,
        **PIPE_TEXT
    )
    if completed.returncode != expect:
        raise SmokeFailure(
            "expected exit %d from %r, got %d\nstdout:\n%s\nstderr:\n%s"
            % (expect, args, completed.returncode, completed.stdout, completed.stderr)
        )
    return completed


def main():
    temp_dir = tempfile.mkdtemp(prefix="bpy-bridge-e2e-")
    token_path = os.path.join(temp_dir, "token")
    script = BRIDGE_CHILD.format(root=ROOT, token_path=token_path)

    bridge = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env(),
        **PIPE_TEXT
    )
    try:
        # First line of stdout is the ready banner with the ephemeral port.
        line = bridge.stdout.readline()
        if not line:
            stderr = bridge.stderr.read()
            raise SmokeFailure("bridge child died before reporting a port:\n%s" % stderr)
        info = json.loads(line)
        port = str(info["port"])

        env = child_env({"BPY_BRIDGE_HOME": temp_dir})

        checks = []

        # 1. ping: the happy path.
        run_cli(["--port", port, "ping"], env)
        checks.append("ping")

        # 2. status: structured data crosses the wire and parses.
        completed = run_cli(["--port", port, "status", "--json"], env)
        payload = json.loads(completed.stdout)
        if payload["status"]["scene"] != "SmokeScene":
            raise SmokeFailure("status returned the wrong scene: %r" % (payload,))
        checks.append("status --json")

        # 3. exec: stdout and the repr'd result both come back.
        completed = run_cli(["--port", port, "exec", "print('hi'); 6 * 7"], env)
        if "hi" not in completed.stdout or "42" not in completed.stdout:
            raise SmokeFailure("exec did not return stdout+result: %r" % (completed.stdout,))
        checks.append("exec")

        # 4. exit code 1 when the remote code raises.
        completed = run_cli(["--port", port, "exec", "raise RuntimeError('nope')"], env, expect=1)
        if "RuntimeError" not in completed.stderr:
            raise SmokeFailure("traceback did not reach stderr: %r" % (completed.stderr,))
        checks.append("exec failure -> exit 1")

        # 5. exit code 4 on a bad token.
        run_cli(["--port", port, "--token", "wrong", "ping"], env, expect=4)
        checks.append("bad token -> exit 4")

        # 6. exit code 3 when nothing is listening.
        run_cli(["--port", "1", "ping"], env, expect=3)
        checks.append("dead port -> exit 3")

        # 7. exit code 2 for an unreadable --file.
        run_cli(["--port", port, "exec", "--file", os.path.join(temp_dir, "absent.py")],
                env, expect=2)
        checks.append("missing --file -> exit 2")

        # 8. the token file the server wrote is where the client looks.
        completed = run_cli(["token-path", "--json"], env)
        reported = json.loads(completed.stdout)["path"]
        if os.path.normcase(reported) != os.path.normcase(token_path):
            raise SmokeFailure("token path mismatch: %r vs %r" % (reported, token_path))
        checks.append("token-path agrees with BPY_BRIDGE_HOME")

        print("OK: %d end-to-end checks passed" % len(checks))
        for check in checks:
            print("  - %s" % check)
        return 0
    finally:
        bridge.terminate()
        try:
            bridge.wait(timeout=10)
        except subprocess.TimeoutExpired:
            bridge.kill()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SmokeFailure as exc:
        print("FAIL: %s" % exc)
        sys.exit(1)
