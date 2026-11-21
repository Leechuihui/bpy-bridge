# -*- coding: utf-8 -*-
"""A fake ``bpy`` module good enough to exercise the bridge.

The real ``bpy`` cannot be installed on PyPI -- it only exists inside Blender --
so the tests carry their own. The fake mirrors the few attributes the bridge
actually touches, and records timer registrations so a test can drive the
main-thread pump by hand, exactly like Blender would.
"""

import threading


class _TimerRegistry(object):
    """Stand-in for ``bpy.app.timers``."""

    def __init__(self):
        self.registered = []
        self.unregistered = []

    def register(self, fn, first_interval=0.0, persistent=False):
        self.registered.append((fn, first_interval, persistent))
        return fn

    def unregister(self, fn):
        self.unregistered.append(fn)

    def tick(self, times=1):
        """Run every registered timer callback *times* times."""
        for _ in range(times):
            for fn, _interval, _persistent in list(self.registered):
                fn()


class _App(object):
    def __init__(self):
        self.version_string = "4.2.0"
        self.timers = _TimerRegistry()


class _Collection(object):
    def __init__(self, name):
        self.name = name


class _Camera(object):
    def __init__(self, name="Camera"):
        self.name = name


class _Render(object):
    engine = "BLENDER_EEVEE_NEXT"


class _Scene(object):
    def __init__(self, name="Scene"):
        self.name = name
        self.render = _Render()
        self.camera = _Camera()
        self.objects = [object() for _ in range(7)]


class _Data(object):
    def __init__(self):
        self.filepath = "C:/fake/scene.blend"
        self.collections = [_Collection("Terrain"), _Collection("Lights_Camera")]


class _Window(object):
    def __init__(self):
        self.screen = "SCREEN"


class _WindowManager(object):
    def __init__(self):
        self.windows = [_Window()]


class _Context(object):
    def __init__(self):
        self.scene = _Scene()
        self.window_manager = _WindowManager()

    def temp_override(self, **kwargs):
        return _NullContext()


class _NullContext(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _ScreenOps(object):
    def __init__(self):
        self.calls = []

    def screenshot(self, filepath=""):
        self.calls.append(filepath)
        return {"FINISHED"}


class _Ops(object):
    def __init__(self):
        self.screen = _ScreenOps()


class FakeBpy(object):
    """Duck-types the slice of ``bpy`` that bpy-bridge depends on."""

    def __init__(self):
        self.app = _App()
        self.data = _Data()
        self.context = _Context()
        self.ops = _Ops()
        self.data_objects = []


def make_fake_bpy():
    return FakeBpy()


def run_pump_until_idle(server, timeout=5.0):
    """Drive the queued work on the *calling* thread, like Blender's timer.

    The real bridge registers ``_pump`` with ``bpy.app.timers``. Outside
    Blender there is no timer loop, so tests call this instead: it stands in
    for "Blender's main thread got around to running the timer".
    """
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if server._queue.empty():
            return True
        server._pump()
        time.sleep(0.001)
    return server._queue.empty()


class PumpingBridge(object):
    """Wraps a BridgeServer and drains its queue from a background thread.

    Used by socket-level tests: the test talks to the server over TCP from the
    main thread, while this thread plays the role of Blender's main thread and
    keeps the pump turning.
    """

    def __init__(self, server):
        self.server = server
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            self.server._pump()
            self._stop.wait(0.005)

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc_info):
        self.stop()
        return False
