"""Small newline-delimited JSON client used by the Max MCP server."""
import json
import os
import socket


HOST = "127.0.0.1"
PORT = int(os.environ.get("MAX_MCP_PORT", "8766"))
TOKEN = os.environ.get("MAX_MCP_TOKEN", "max-mcp-local")


def request(method, params=None, timeout=120):
    packet = {"id": 1, "token": TOKEN, "method": method,
              "params": params or {}, "timeout": timeout}
    with socket.create_connection((HOST, PORT), timeout=min(timeout, 10)) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
        data = bytearray()
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
    if not data:
        raise RuntimeError("Max MCP returned no response")
    result = json.loads(data.decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Max command failed"))
    return result.get("data")

