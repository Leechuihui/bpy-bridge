# -*- coding: utf-8 -*-
"""Tests for the in-Blender server, without a Blender."""

import json
import os
import socket

import pytest

from bpy_bridge import protocol
from bpy_bridge.server import (
    BridgeHelper,
    BridgeServer,
    default_token_path,
    ensure_token,
    is_loopback,
    read_token,
    write_token,
)

from fake_bpy import PumpingBridge, make_fake_bpy, run_pump_until_idle


# --------------------------------------------------------------------- tokens
def test_ensure_token_creates_and_persists(tmp_path):
    path = str(tmp_path / "token")
    token, written = ensure_token(token_path=path)
    assert len(token) >= 32
    assert written == path
    assert read_token(path) == token


def test_ensure_token_is_stable_across_calls(tmp_path):
    path = str(tmp_path / "token")
    first, _ = ensure_token(token_path=path)
    second, _ = ensure_token(token_path=path)
    assert first == second


def test_ensure_token_honours_explicit_token(tmp_path):
    path = str(tmp_path / "token")
    token, _ = ensure_token(token="my-fixed-token", token_path=path)
    assert token == "my-fixed-token"


def test_ensure_token_persists_an_explicit_token(tmp_path):
    """Regression: a server started with an explicit token must write it out.

    The client locates the token by reading this file. If an explicit token were
    kept in memory only, every client following the documented workflow would
    read a stale value and fail authentication against a healthy bridge. This
    was caught by tests/e2e_smoke.py, not by the unit tests.
    """
    path = str(tmp_path / "token")
    ensure_token(token="my-fixed-token", token_path=path)
    assert read_token(path) == "my-fixed-token"


def test_ensure_token_can_skip_persistence(tmp_path):
    path = str(tmp_path / "token")
    token, _ = ensure_token(token="kept-in-memory", token_path=path, persist=False)
    assert token == "kept-in-memory"
    assert read_token(path) is None


def test_server_persists_explicit_token_for_clients(tmp_path):
    path = str(tmp_path / "token")
    server = BridgeServer(port=0, token="explicit", token_path=path,
                          bpy_module=make_fake_bpy())
    assert server.token == "explicit"
    assert read_token(path) == "explicit"


def test_read_token_returns_none_for_missing_file(tmp_path):
    assert read_token(str(tmp_path / "nope")) is None


def test_read_token_returns_none_for_blank_file(tmp_path):
    path = tmp_path / "token"
    path.write_text("   \n", encoding="utf-8")
    assert read_token(str(path)) is None


def test_write_token_is_not_world_readable(tmp_path):
    path = str(tmp_path / "token")
    write_token("secret", path)
    if os.name == "posix":
        mode = os.stat(path).st_mode & 0o777
        assert mode & 0o077 == 0, "token file must not be readable by others"


def test_default_token_path_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BPY_BRIDGE_HOME", str(tmp_path))
    assert default_token_path() == str(tmp_path / "token")


# ------------------------------------------------------------------ loopback
@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.53", "::1", "localhost"])
def test_is_loopback_accepts_local_addresses(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.1", "::"])
def test_is_loopback_rejects_routable_addresses(host):
    assert is_loopback(host) is False


def test_server_refuses_non_loopback_bind(tmp_path):
    with pytest.raises(ValueError, match="not a loopback"):
        BridgeServer(host="0.0.0.0", port=0, token_path=str(tmp_path / "t"),
                     bpy_module=make_fake_bpy())


def test_server_allows_non_loopback_when_explicit(tmp_path):
    server = BridgeServer(host="0.0.0.0", port=0, token_path=str(tmp_path / "t"),
                          bpy_module=make_fake_bpy(), allow_remote=True)
    assert server.allow_remote is True


# ------------------------------------------------------------------ fixture
@pytest.fixture
def bridge(tmp_path):
    """A server with a fake bpy, a throwaway token, and no socket yet."""
    server = BridgeServer(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "token"),
        bpy_module=make_fake_bpy(),
    )
    yield server
    server.stop()


@pytest.fixture
def live(bridge):
    """A bridge that is listening, with a background thread playing Blender."""
    bridge.start()
    pumper = PumpingBridge(bridge).start()
    yield bridge
    pumper.stop()


def _frame(server, **kwargs):
    kwargs.setdefault("token", server.token)
    return protocol.encode_request(**kwargs)


def _decode(payload):
    return json.loads(payload.decode("utf-8"))


# ------------------------------------------------------------- handle_frame
def test_ping_returns_pong(bridge):
    response = _decode(bridge.handle_frame(_frame(bridge, op=protocol.OP_PING)))
    assert response["ok"] is True
    assert response["kind"] == "ok"
    assert response["result"] == "pong"


def test_bad_token_is_rejected_with_kind_auth(bridge):
    response = _decode(bridge.handle_frame(_frame(bridge, op=protocol.OP_PING, token="wrong")))
    assert response["ok"] is False
    assert response["kind"] == protocol.KIND_AUTH


def test_missing_token_is_rejected(bridge):
    response = _decode(bridge.handle_frame(_frame(bridge, op=protocol.OP_PING, token="")))
    assert response["kind"] == protocol.KIND_AUTH


def test_malformed_json_yields_protocol_error(bridge):
    response = _decode(bridge.handle_frame(b"{not json\n"))
    assert response["ok"] is False
    assert response["kind"] == protocol.KIND_PROTOCOL


def test_request_id_is_echoed_on_success(bridge):
    response = _decode(bridge.handle_frame(_frame(bridge, op=protocol.OP_PING, request_id="r-9")))
    assert response["request_id"] == "r-9"


def test_request_id_is_echoed_on_auth_failure(bridge):
    payload = _frame(bridge, op=protocol.OP_PING, token="nope", request_id="r-10")
    response = _decode(bridge.handle_frame(payload))
    assert response["request_id"] == "r-10"


def test_exec_evaluates_expression_and_returns_repr(bridge):
    bridge.start()
    payload = _frame(bridge, code="1 + 1")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert response["result"] == "2"


def test_exec_runs_statements(bridge):
    bridge.start()
    payload = _frame(bridge, code="x = 41\nx += 1")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert response["result"] is None


def test_exec_namespace_persists_between_requests(bridge):
    bridge.start()
    with PumpingBridge(bridge):
        _decode(bridge.handle_frame(_frame(bridge, code="carried = 123")))
        response = _decode(bridge.handle_frame(_frame(bridge, code="carried")))
    assert response["result"] == "123"


def test_exec_returns_trailing_expression_after_statements(bridge):
    """Regression: REPL semantics, not plain exec.

    ``print('hi'); 6 * 7`` must yield both the captured stdout and the value of
    the trailing expression. Compiling the whole snippet as an expression and
    falling back to exec() dropped the value for every multi-statement snippet,
    which is exactly what people send interactively. Caught by
    tests/e2e_smoke.py.
    """
    bridge.start()
    payload = _frame(bridge, code="print('hi')\n6 * 7")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert "hi" in response["stdout"]
    assert response["result"] == "42"


def test_exec_returns_trailing_expression_after_assignment(bridge):
    bridge.start()
    payload = _frame(bridge, code="total = 10\ntotal * 2")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["result"] == "20"


def test_exec_trailing_expression_sees_prior_assignments(bridge):
    bridge.start()
    payload = _frame(bridge, code="items = [1, 2, 3]\nlen(items)")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["result"] == "3"


def test_exec_ending_in_none_returning_call_yields_null(bridge):
    """Regression: a trailing expression that evaluates to None returns null.

    ``repr(None)`` is the string ``"None"``, which is noise in --json output and
    forces every consumer to special-case it. A Python REPL prints nothing for
    None; this matches that.
    """
    bridge.start()
    payload = _frame(bridge, code="print('done')")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert response["result"] is None
    assert "done" in response["stdout"]


def test_exec_none_literal_returns_null(bridge):
    bridge.start()
    payload = _frame(bridge, code="None")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["result"] is None


def test_exec_statements_only_still_returns_none(bridge):
    bridge.start()
    payload = _frame(bridge, code="a = 1\nb = 2")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert response["result"] is None


def test_exec_raises_from_trailing_expression(bridge):
    bridge.start()
    payload = _frame(bridge, code="x = 1\n1 / 0")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is False
    assert response["kind"] == protocol.KIND_EXEC
    assert "ZeroDivisionError" in response["error"]


def test_exec_captures_stdout(bridge):
    bridge.start()
    payload = _frame(bridge, code="print('hello from blender')")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert "hello from blender" in response["stdout"]


def test_exec_reports_traceback_with_kind_exec(bridge):
    bridge.start()
    payload = _frame(bridge, code="1 / 0")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is False
    assert response["kind"] == protocol.KIND_EXEC
    assert "ZeroDivisionError" in response["error"]


def test_exec_timeout_is_reported_when_pump_never_runs(bridge):
    bridge.start()
    payload = _frame(bridge, code="1 + 1", timeout=0.05)
    response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is False
    assert response["kind"] == protocol.KIND_TIMEOUT


def test_status_is_serialised_as_json(bridge):
    bridge.start()
    payload = _frame(bridge, op=protocol.OP_STATUS)
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    info = json.loads(response["result"])
    assert info["blender"] == "4.2.0"
    assert info["scene"] == "Scene"
    assert info["objects"] == 7


def test_bpy_is_injected_into_the_namespace(bridge):
    """Regression: the README's headline example must actually work.

    The quickstart shows ``bpy-bridge exec 'len(bpy.data.objects)'``. The first
    live run against a real 5,757-object scene raised ``NameError: name 'bpy' is
    not defined`` because only ``bridge`` was injected. Documentation that shows
    a command which fails is worse than no documentation, so this pins the
    behaviour: inside Blender, ``bpy`` is simply there.
    """
    bridge.start()
    payload = _frame(bridge, code="bpy.app.version_string")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["ok"] is True
    assert response["result"] == "'4.2.0'"


def test_injected_bpy_is_the_real_module_object(bridge):
    bridge.start()
    payload = _frame(bridge, code="bpy is bridge.bpy")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["result"] == "True"


def test_ensure_bpy_is_a_noop_when_bpy_is_unavailable(tmp_path):
    """Outside Blender, ``_ensure_bpy`` must not invent a module."""
    server = BridgeServer(port=0, token_path=str(tmp_path / "t"), bpy_module=None)
    server._ensure_bpy()
    assert "bpy" not in server._namespace


def test_bridge_helper_is_injected_into_the_namespace(bridge):
    bridge.start()
    payload = _frame(bridge, code="bridge.bpy.app.version_string")
    with PumpingBridge(bridge):
        response = _decode(bridge.handle_frame(payload))
    assert response["result"] == "'4.2.0'"


# ---------------------------------------------------------------- over TCP
def test_end_to_end_over_tcp(live):
    from bpy_bridge import BridgeClient

    client = BridgeClient(host=live.host, port=live.port, token=live.token)
    result = client.exec("21 * 2")
    assert result.ok is True
    assert result.result == "42"


def test_tcp_rejects_wrong_token(live):
    from bpy_bridge import BridgeAuthError, BridgeClient

    client = BridgeClient(host=live.host, port=live.port, token="definitely-wrong")
    with pytest.raises(BridgeAuthError):
        client.ping()


def test_tcp_ping(live):
    from bpy_bridge import BridgeClient

    assert BridgeClient(host=live.host, port=live.port, token=live.token).ping() is True


def test_tcp_status(live):
    from bpy_bridge import BridgeClient

    info = BridgeClient(host=live.host, port=live.port, token=live.token).status()
    assert info["engine"] == "BLENDER_EEVEE_NEXT"


def test_tcp_remote_exception_raises_remote_exec_error(live):
    from bpy_bridge import BridgeClient, RemoteExecError

    client = BridgeClient(host=live.host, port=live.port, token=live.token)
    result = client.exec("raise ValueError('boom')")
    assert result.ok is False
    with pytest.raises(RemoteExecError):
        result.raise_for_status()


def test_tcp_screenshot_reaches_bpy_ops(live):
    from bpy_bridge import BridgeClient

    client = BridgeClient(host=live.host, port=live.port, token=live.token)
    result = client.screenshot("C:/tmp/ui.png")
    assert result.ok is True
    # The server absolutizes before handing the path to the operator, so the
    # expected value has to be absolutized the same way. Hard-coding the Windows
    # form ("C:\\tmp\\ui.png") passed here and failed on Linux and macOS, where
    # "C:/tmp/ui.png" is not absolute and gets joined onto the working directory.
    assert live.bpy.ops.screen.calls == [os.path.abspath("C:/tmp/ui.png")]


def test_tcp_run_file_executes_local_file(live, tmp_path):
    from bpy_bridge import BridgeClient

    script = tmp_path / "do.py"
    script.write_text("from_bridge = 'ran'\n", encoding="utf-8")
    client = BridgeClient(host=live.host, port=live.port, token=live.token)
    assert client.run_file(str(script)).ok is True
    assert client.exec("from_bridge").result == "'ran'"


def test_oversized_frame_is_refused(live):
    with socket.create_connection((live.host, live.port), timeout=5) as sock:
        sock.sendall(b"x" * (live.max_frame_bytes + 10) + b"\n")
        payload = sock.recv(65536)
    response = json.loads(payload.decode("utf-8"))
    assert response["ok"] is False
    assert response["kind"] == protocol.KIND_PROTOCOL


def test_server_stops_cleanly_and_frees_the_port(live):
    host, port = live.host, live.port
    live.stop()
    assert live.running is False
    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=0.5)


def test_stop_is_idempotent(bridge):
    bridge.start()
    bridge.stop()
    bridge.stop()
    assert bridge.running is False


def test_start_is_idempotent(bridge):
    bridge.start()
    first_port = bridge.port
    bridge.start()
    assert bridge.port == first_port


# ---------------------------------------------------------------- helper API
def test_start_forwards_every_server_option(tmp_path, monkeypatch):
    """The facade used by autostart scripts must not drop supported options.

    ``start()`` is what an autostart file calls, so a setting it cannot express
    is effectively undocumented even if ``BridgeServer`` supports it. This pins
    the forwarding.
    """
    from bpy_bridge import server as server_module

    captured = {}

    class _RecordingServer(BridgeServer):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super(_RecordingServer, self).__init__(**kwargs)

    monkeypatch.setattr(server_module, "BridgeServer", _RecordingServer)
    monkeypatch.setattr(server_module, "_ACTIVE", None)

    server_module.start(
        port=0,
        token_path=str(tmp_path / "token"),
        bpy_module=make_fake_bpy(),
        max_frame_bytes=1024,
        persist_token=False,
        verbose=False,
    )
    try:
        assert captured["max_frame_bytes"] == 1024
        assert captured["persist_token"] is False
        assert captured["host"] == "127.0.0.1"
    finally:
        server_module.stop()


def test_start_is_idempotent_inside_blender(tmp_path, monkeypatch):
    from bpy_bridge import server as server_module

    monkeypatch.setattr(server_module, "_ACTIVE", None)
    first = server_module.start(port=0, token_path=str(tmp_path / "token"),
                                bpy_module=make_fake_bpy(), verbose=False)
    try:
        second = server_module.start(port=0, token_path=str(tmp_path / "token"),
                                     bpy_module=make_fake_bpy(), verbose=False)
        assert second is first
    finally:
        server_module.stop()


def test_helper_status_without_bpy_raises_import_error():
    helper = BridgeHelper(bpy_module=None)
    with pytest.raises(ImportError):
        helper.bpy


def test_helper_exec_file_keeps_namespace(tmp_path):
    fake = make_fake_bpy()
    helper = BridgeHelper(fake)
    namespace = {"__name__": "__test__"}
    helper._bind(namespace)
    script = tmp_path / "s.py"
    script.write_text("value = 99\n", encoding="utf-8")
    helper.exec_file(str(script))
    assert namespace["value"] == 99


def test_helper_shot_needs_a_window():
    class _NoWindows(object):
        windows = []

    fake = make_fake_bpy()
    fake.context.window_manager = _NoWindows()
    with pytest.raises(RuntimeError, match="no Blender window"):
        BridgeHelper(fake).shot("x.png")
