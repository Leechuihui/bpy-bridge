# -*- coding: utf-8 -*-
"""Tests for the CLI: exit codes, --json shape, and argument handling."""

import json

import pytest

from bpy_bridge import cli, protocol
from bpy_bridge.client import ExecResult
from bpy_bridge.protocol import BridgeAuthError, BridgeTimeout, BridgeUnreachable, RemoteExecError


class _FakeClient(object):
    """Stands in for BridgeClient inside the CLI commands."""

    #: Overridable per test; a production scene has dozens of collections.
    collections = ()

    def __init__(self, *args, **kwargs):
        self.args = (args, kwargs)

    def ping(self):
        return True

    def status(self):
        info = {"blender": "4.2.0", "scene": "Scene", "objects": 3}
        if self.collections:
            info["collections"] = list(self.collections)
        return info

    def exec(self, code, timeout=None):
        if code.strip() == "explode":
            return ExecResult(ok=False, kind="exec", error="Traceback: ValueError")
        if code.strip() == "slow":
            return ExecResult(ok=False, kind="timeout", error="no result after 5s")
        return ExecResult(ok=True, kind="ok", result="42", stdout="printed\n", duration_ms=2.5)

    def screenshot(self, path):
        return ExecResult(ok=True, kind="ok", result=str(path))


class _CollectionClient(_FakeClient):
    """A fake client whose status reports *names* as the collection list."""

    def __init__(self, names):
        super(_CollectionClient, self).__init__()
        self.collections = tuple(names)


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    monkeypatch.setattr(cli, "_client", lambda args: _FakeClient())


def run(argv):
    return cli.main(argv)


# ------------------------------------------------------------------- exit codes
def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as caught:
        run(["--version"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "bpy-bridge" in out
    assert "protocol v1" in out


def test_no_command_prints_help_and_exits_usage(capsys):
    assert run([]) == cli.EXIT_USAGE
    assert "usage" in capsys.readouterr().out.lower()


def test_ping_exits_zero(capsys):
    assert run(["ping"]) == cli.EXIT_OK
    assert "pong" in capsys.readouterr().out


def test_status_exits_zero_and_prints_fields(capsys):
    assert run(["status"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "blender:" in out
    assert "4.2.0" in out


def test_status_json_shape(capsys):
    assert run(["status", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"]["scene"] == "Scene"


def test_status_previews_collections_instead_of_wrapping(capsys, monkeypatch):
    """Regression: dozens of collection names must not become one wall of text.

    The first live run against a 45-collection production scene printed every
    name on a single line, which is unreadable in a terminal and useless in a
    screenshot. Show a count and a short preview; --json keeps the full list.
    """
    names = ["Collection_%02d" % index for index in range(45)]
    monkeypatch.setattr(cli, "_client", lambda args: _CollectionClient(names))

    assert run(["status"]) == cli.EXIT_OK
    out = capsys.readouterr().out

    assert "collections: 45" in out
    assert "first:" in out
    assert names[0] in out
    # The preview is bounded, and the remainder is summarised rather than dumped.
    assert names[cli.COLLECTION_PREVIEW] not in out
    assert "... and %d more" % (len(names) - cli.COLLECTION_PREVIEW) in out


def test_status_json_keeps_every_collection(capsys, monkeypatch):
    names = ["Collection_%02d" % index for index in range(45)]
    monkeypatch.setattr(cli, "_client", lambda args: _CollectionClient(names))

    assert run(["status", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"]["collections"] == names


def test_status_without_collections_omits_the_section(capsys):
    assert run(["status"]) == cli.EXIT_OK
    assert "collections:" not in capsys.readouterr().out


def test_exec_prints_stdout_and_result(capsys):
    assert run(["exec", "1 + 1"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "printed" in out
    assert "42" in out


def test_exec_quiet_suppresses_output(capsys):
    assert run(["exec", "1 + 1", "--quiet"]) == cli.EXIT_OK
    assert capsys.readouterr().out == ""


def test_exec_json_payload(capsys):
    assert run(["exec", "1 + 1", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"] == "42"
    assert payload["source"] == "<argv>"


def test_exec_remote_failure_exits_one(capsys):
    assert run(["exec", "explode"]) == cli.EXIT_REMOTE
    assert "ValueError" in capsys.readouterr().err


def test_exec_timeout_exits_five(capsys):
    assert run(["exec", "slow"]) == cli.EXIT_TIMEOUT


def test_exec_without_code_or_file_exits_usage(capsys):
    assert run(["exec"]) == cli.EXIT_USAGE
    assert "needs code or --file" in capsys.readouterr().err


def test_exec_from_file(capsys, tmp_path):
    script = tmp_path / "s.py"
    script.write_text("1 + 1\n", encoding="utf-8")
    assert run(["exec", "--file", str(script)]) == cli.EXIT_OK


def test_exec_from_file_missing_is_a_usage_error(capsys, tmp_path):
    # A missing script is the user's typo, not a connectivity problem.
    assert run(["exec", "--file", str(tmp_path / "absent.py")]) == cli.EXIT_USAGE
    assert "cannot read" in capsys.readouterr().err


def test_shot_prints_path(capsys):
    assert run(["shot", "ui.png"]) == cli.EXIT_OK
    assert "ui.png" in capsys.readouterr().out


def test_token_path_reports_location(capsys):
    assert run(["token-path"]) == cli.EXIT_OK
    assert "token" in capsys.readouterr().out


def test_token_command_prints_token(capsys, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("abc123\n", encoding="utf-8")
    assert run(["--token-file", str(token_file), "token"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "abc123"


def test_token_command_without_file_exits_auth(capsys, tmp_path):
    assert run(["--token-file", str(tmp_path / "absent"), "token"]) == cli.EXIT_AUTH


# ------------------------------------------------------------- error mapping
def test_main_maps_unreachable(monkeypatch, capsys):
    def boom(args):
        raise BridgeUnreachable("nothing listening")

    monkeypatch.setattr(cli, "_client", boom)
    assert run(["ping"]) == cli.EXIT_UNREACHABLE


def test_main_maps_auth_error(monkeypatch):
    def boom(args):
        raise BridgeAuthError("bad token")

    monkeypatch.setattr(cli, "_client", boom)
    assert run(["ping"]) == cli.EXIT_AUTH


def test_main_maps_timeout(monkeypatch):
    def boom(args):
        raise BridgeTimeout("too slow")

    monkeypatch.setattr(cli, "_client", boom)
    assert run(["ping"]) == cli.EXIT_TIMEOUT


def test_main_maps_remote_exec_error(monkeypatch):
    def boom(args):
        raise RemoteExecError("kaboom", "tb", "out")

    monkeypatch.setattr(cli, "_client", boom)
    assert run(["exec", "x"]) == cli.EXIT_REMOTE


def test_json_error_payload_is_well_formed(monkeypatch, capsys):
    def boom(args):
        raise BridgeUnreachable("nothing listening")

    monkeypatch.setattr(cli, "_client", boom)
    assert run(["--json", "ping"]) == cli.EXIT_UNREACHABLE
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["exit"] == cli.EXIT_UNREACHABLE


def test_remote_warning_goes_to_stderr(capsys):
    assert run(["--host", "10.0.0.5", "ping"]) == cli.EXIT_OK
    assert "not a loopback address" in capsys.readouterr().err


def test_no_remote_warning_for_loopback(capsys):
    assert run(["ping"]) == cli.EXIT_OK
    assert capsys.readouterr().err == ""
