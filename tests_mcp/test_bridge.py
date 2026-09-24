import concurrent.futures
import io
import json
import socket
import threading
import time
from pathlib import Path
import re

import pytest

from maya_mcp.bridge import Bridge
from maya_mcp.connection import encode_packet, read_packet
from maya_mcp.install import install_startup


@pytest.fixture
def bridge():
    calls = []
    def dispatch(method, params):
        calls.append((method, threading.get_ident()))
        if method == "fail":
            raise RuntimeError("intentional failure")
        return params
    b = Bridge(dispatch, {"host": "127.0.0.1", "port": 0, "token": "x" * 64})
    b.calls = calls
    yield b
    b.stop()


def send(b, **overrides):
    packet = {"id": "test", "token": "x" * 64, "method": "echo", "params": {"中文": 12}, "timeout": 1}
    packet.update(overrides)
    with socket.create_connection(b.server.server_address, timeout=3) as sock:
        sock.settimeout(4)
        data = encode_packet(packet)
        # Exercise fragmented TCP input rather than assuming one recv is a packet.
        for i in range(0, len(data), 7):
            sock.sendall(data[i:i + 7])
        return read_packet(sock.makefile("rb"))


def run_pumped(b, **kwargs):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(send, b, **kwargs)
        until = time.monotonic() + 4
        while not future.done() and time.monotonic() < until:
            b.drain()
            time.sleep(.005)
        return future.result(timeout=1)


def test_main_thread_and_unicode(bridge):
    result = run_pumped(bridge)
    assert result == {"id": "test", "ok": True, "data": {"中文": 12}}
    assert bridge.calls == [("echo", threading.get_ident())]


def test_bad_auth_never_dispatches(bridge):
    result = run_pumped(bridge, token="wrong")
    assert result["ok"] is False
    assert bridge.calls == []


def test_exception_is_not_reexecuted(bridge):
    result = run_pumped(bridge, method="fail")
    assert result["ok"] is False
    assert "intentional failure" in result["error"]
    assert len(bridge.calls) == 1


def test_expired_queued_command_never_executes(bridge):
    result = send(bridge)
    assert "cancelled" in result["error"]
    bridge.drain()
    assert not bridge.calls


def test_worker_cannot_drain(bridge):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(bridge.drain)
        with pytest.raises(RuntimeError, match="main thread"):
            future.result()


def test_packet_rejects_unterminated_input():
    with pytest.raises(ValueError):
        read_packet(io.BytesIO(b'{"id":1}'))


def test_install_preserves_existing_bytes_and_is_idempotent(tmp_path):
    original = b"# existing\r\nprint('keep me')\r\n"
    path = tmp_path / "userSetup.py"
    path.write_bytes(original)
    install_startup(tmp_path)
    first = path.read_bytes()
    install_startup(tmp_path)
    assert path.read_bytes() == first
    assert first.startswith(original)
    assert first.count(b"# >>> Maya MCP") == 1
    install_startup(tmp_path, remove=True)
    assert path.read_bytes() == original


def test_drag_installer_uses_one_valid_string_literal():
    source = (Path(__file__).resolve().parents[1] / "install_maya_mcp.mel").read_text(encoding="utf-8")
    # MEL does not concatenate adjacent literals as Python does.
    match = re.search(r'python\(("(?:[^"\\]|\\.)*")\);', source)
    assert match, "python() must receive one complete MEL string expression"
    payload = json.loads(match.group(1))
    compile(payload, "<MEL installer payload>", "exec")
    assert "activate_maya_mcp.py" in payload
