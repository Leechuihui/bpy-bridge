# -*- coding: utf-8 -*-
"""Tests for the client, driven against a stub server rather than a socket."""

import pytest

from bpy_bridge import protocol
from bpy_bridge.client import BridgeClient, ExecResult
from bpy_bridge.protocol import BridgeAuthError, BridgeTimeout, ProtocolError, RemoteExecError


class StubClient(BridgeClient):
    """A client whose transport is a canned response instead of a socket."""

    def __init__(self, response=None, **kwargs):
        kwargs.setdefault("token", "stub-token")
        super(StubClient, self).__init__(**kwargs)
        self.response = response or {}
        self.requests = []

    def _roundtrip(self, **request_kwargs):
        self.requests.append(request_kwargs)
        return self.response


def test_exec_returns_ok_result():
    client = StubClient({"ok": True, "kind": "ok", "result": "42", "stdout": "", "duration_ms": 1.0})
    result = client.exec("40 + 2")
    assert result.ok is True
    assert result.result == "42"
    assert result.duration_ms == 1.0


def test_exec_passes_code_and_timeout():
    client = StubClient({"ok": True, "kind": "ok", "result": None})
    client.exec("pass", timeout=12.5)
    assert client.requests[0]["code"] == "pass"
    assert client.requests[0]["timeout"] == 12.5


def test_exec_rejects_non_string_code():
    client = StubClient()
    with pytest.raises(TypeError, match="code must be a str"):
        client.exec(b"print(1)")


def test_exec_or_raise_returns_result():
    client = StubClient({"ok": True, "kind": "ok", "result": "'value'"})
    assert client.exec_or_raise("'value'") == "'value'"


def test_exec_or_raise_raises_on_failure():
    client = StubClient({"ok": False, "kind": "exec", "error": "Traceback..."})
    with pytest.raises(RemoteExecError):
        client.exec_or_raise("1/0")


def test_raise_for_status_auth():
    result = ExecResult(ok=False, kind="auth", error="bad token")
    with pytest.raises(BridgeAuthError):
        result.raise_for_status()


def test_raise_for_status_timeout():
    result = ExecResult(ok=False, kind="timeout", error="slow")
    with pytest.raises(BridgeTimeout):
        result.raise_for_status()


def test_raise_for_status_protocol():
    result = ExecResult(ok=False, kind="protocol", error="garbage")
    with pytest.raises(ProtocolError):
        result.raise_for_status()


def test_remote_exec_error_carries_stdout():
    result = ExecResult(ok=False, kind="exec", error="boom", stdout="printed first\n")
    with pytest.raises(RemoteExecError) as caught:
        result.raise_for_status()
    assert caught.value.stdout == "printed first\n"


def test_exec_result_is_falsy_on_failure():
    assert not ExecResult(ok=False)
    assert ExecResult(ok=True)


def test_status_parses_json_payload():
    info = {"blender": "4.2.0", "scene": "Scene"}
    client = StubClient({"ok": True, "kind": "ok", "result": '{"blender": "4.2.0", "scene": "Scene"}'})
    assert client.status() == info


def test_status_survives_non_json_payload():
    client = StubClient({"ok": True, "kind": "ok", "result": "not json at all"})
    assert client.status() == {"raw": "not json at all"}


def test_ping_raises_on_auth_failure():
    client = StubClient({"ok": False, "kind": "auth", "error": "bad token"})
    with pytest.raises(BridgeAuthError):
        client.ping()


def test_client_reads_token_from_disk(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("from-disk\n", encoding="utf-8")
    client = BridgeClient(token_path=str(token_file))
    assert client.token == "from-disk"


def test_client_from_token_file_helper(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("disk-token\n", encoding="utf-8")
    client = BridgeClient.from_token_file(str(token_file))
    assert client.token == "disk-token"


def test_client_from_token_file_missing(tmp_path):
    with pytest.raises(BridgeAuthError, match="no token found"):
        BridgeClient.from_token_file(str(tmp_path / "absent"))


def test_run_file_escapes_backslashes():
    client = StubClient({"ok": True, "kind": "ok", "result": None})
    client.run_file(r"C:\Users\me\script.py")
    sent = client.requests[0]["code"]
    assert "bridge.exec_file" in sent
    assert r"C:\\Users\\me\\script.py" in sent


def test_screenshot_quotes_path():
    client = StubClient({"ok": True, "kind": "ok", "result": None})
    client.screenshot("C:/tmp/ui.png")
    assert 'bridge.shot(r"C:/tmp/ui.png")' == client.requests[0]["code"]


def test_repr_is_readable():
    assert repr(BridgeClient(host="127.0.0.1", port=9876, token="x")) == "<BridgeClient 127.0.0.1:9876>"


def test_exec_result_repr_marks_failure():
    assert "error(exec)" in repr(ExecResult(ok=False, kind="exec"))
