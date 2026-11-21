# -*- coding: utf-8 -*-
"""bpy-bridge -- drive a *running* Blender from any process, in one line.

Blender's Python API is not thread safe and its headless mode is a different
universe from the UI. bpy-bridge closes that gap: it starts a loopback TCP
server inside a live Blender session, queues incoming code onto the main thread
with ``bpy.app.timers``, and hands stdout, the return value, and the traceback
back to whoever asked.

    from bpy_bridge import BridgeClient

    bridge = BridgeClient()
    print(bridge.exec("len(bpy.data.objects)").result)

Typical uses: watch a viewport while a scripted asset build runs, poke at a
scene from a notebook, let an LLM agent inspect what it just created, or drive
Blender from a CI step that already has it open.

Nothing here imports ``bpy`` until it is genuinely inside Blender.
"""

from .protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    BridgeAuthError,
    BridgeError,
    BridgeTimeout,
    BridgeUnreachable,
    ProtocolError,
    RemoteExecError,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
    make_request,
    make_response,
)
from .client import BridgeClient, ExecResult
from .server import (
    BridgeHelper,
    BridgeServer,
    default_token_path,
    ensure_token,
    is_loopback,
    read_token,
    write_token,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # protocol
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "MAX_FRAME_BYTES",
    "PROTOCOL_VERSION",
    "make_request",
    "make_response",
    "encode_request",
    "encode_response",
    "decode_request",
    "decode_response",
    # errors
    "BridgeError",
    "BridgeAuthError",
    "BridgeTimeout",
    "BridgeUnreachable",
    "ProtocolError",
    "RemoteExecError",
    # client
    "BridgeClient",
    "ExecResult",
    # server
    "BridgeServer",
    "BridgeHelper",
    "default_token_path",
    "ensure_token",
    "read_token",
    "write_token",
    "is_loopback",
]
