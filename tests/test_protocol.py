# -*- coding: utf-8 -*-
"""Tests for the wire protocol: encoding, decoding, and validation."""

import json

import pytest

from bpy_bridge import protocol


def test_encode_request_roundtrips_through_decode():
    raw = protocol.encode_request(code="1 + 1", token="t0ken", request_id="abc")
    assert raw.endswith(b"\n")
    decoded = protocol.decode_request(raw)
    assert decoded["code"] == "1 + 1"
    assert decoded["token"] == "t0ken"
    assert decoded["op"] == protocol.OP_EXEC
    assert decoded["request_id"] == "abc"
    assert decoded["protocol"] == protocol.PROTOCOL_VERSION


def test_decode_request_defaults_op_to_exec():
    decoded = protocol.decode_request(json.dumps({"code": "pass"}).encode("utf-8"))
    assert decoded["op"] == protocol.OP_EXEC
    assert decoded["token"] == ""
    assert decoded["timeout"] == protocol.DEFAULT_TIMEOUT


def test_decode_request_rejects_unknown_op():
    with pytest.raises(protocol.ProtocolError, match="unknown op"):
        protocol.decode_request(json.dumps({"op": "rm -rf"}).encode("utf-8"))


def test_decode_request_rejects_non_object():
    with pytest.raises(protocol.ProtocolError, match="JSON object"):
        protocol.decode_request(b"[1, 2, 3]\n")


def test_decode_request_rejects_invalid_json():
    with pytest.raises(protocol.ProtocolError, match="not valid JSON"):
        protocol.decode_request(b"{nope\n")


def test_decode_request_rejects_empty_frame():
    with pytest.raises(protocol.ProtocolError, match="empty"):
        protocol.decode_request(b"   \n")


def test_decode_request_rejects_bad_utf8():
    with pytest.raises(protocol.ProtocolError, match="UTF-8"):
        protocol.decode_request(b"\xff\xfe\x00\n")


def test_decode_request_rejects_non_string_code():
    with pytest.raises(protocol.ProtocolError, match="code must be a string"):
        protocol.decode_request(json.dumps({"code": 42}).encode("utf-8"))


@pytest.mark.parametrize("bad_timeout", ["nope", None, -5, 0])
def test_decode_request_normalises_bad_timeout(bad_timeout):
    payload = {"code": "pass", "timeout": bad_timeout}
    decoded = protocol.decode_request(json.dumps(payload).encode("utf-8"))
    assert decoded["timeout"] == protocol.DEFAULT_TIMEOUT


def test_make_request_validates_op():
    with pytest.raises(protocol.ProtocolError, match="unknown op"):
        protocol.make_request(op="explode")


def test_make_request_validates_code_type():
    with pytest.raises(protocol.ProtocolError, match="code must be a string"):
        protocol.make_request(code=b"print(1)")


def test_encode_response_sets_ok_from_kind():
    raw = protocol.encode_response(kind=protocol.KIND_AUTH, error="bad token")
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["kind"] == "auth"
    assert payload["error"] == "bad token"


def test_encode_response_rejects_unknown_kind():
    with pytest.raises(protocol.ProtocolError, match="unknown response kind"):
        protocol.make_response(kind="meltdown")


def test_decode_response_tolerates_missing_fields():
    payload = protocol.decode_response(b'{"ok": true}\n')
    assert payload["ok"] is True
    assert payload["kind"] == protocol.KIND_OK
    assert payload["stdout"] == ""
    assert payload["result"] is None


def test_decode_response_marks_failure_kind():
    payload = protocol.decode_response(b'{"ok": false}\n')
    assert payload["kind"] == protocol.KIND_INTERNAL


def test_unicode_survives_the_roundtrip():
    text = "print('\u4e2d\u6587 \u2014 \u00e9\u00e8')"
    decoded = protocol.decode_request(protocol.encode_request(code=text))
    assert decoded["code"] == text


def test_duration_is_rounded_to_three_places():
    response = protocol.make_response(duration_ms=12.3456789)
    assert response["duration_ms"] == 12.346
