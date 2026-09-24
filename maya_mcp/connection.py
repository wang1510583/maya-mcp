"""Bounded, authenticated newline JSON transport. No automatic command retries."""
import json
import os
from pathlib import Path
import secrets
import socket
import uuid

MAX_BYTES = 16 * 1024 * 1024
DEFAULT_PORT = 9877
INSTALLATION_PATH = Path(__file__).resolve().parents[1] / ".maya-mcp-runtime.json"


def settings_path():
    override = os.environ.get("MAYA_MCP_CONFIG")
    if override:
        return Path(override)
    # Maya launched from a DCC launcher can inherit different APPDATA settings.
    # Pin both halves of this installation to the same file without copying tokens.
    if INSTALLATION_PATH.exists():
        return Path(json.loads(INSTALLATION_PATH.read_text(encoding="utf-8"))["config_path"])
    return Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "MayaMCP" / "connection.json"


def read_settings():
    cfg = json.loads(settings_path().read_text(encoding="utf-8"))
    if cfg.get("host") != "127.0.0.1" or len(cfg.get("token", "")) < 32:
        raise ValueError("Invalid Maya MCP settings: loopback and authentication required")
    return cfg


def ensure_settings():
    path = settings_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = {"host": "127.0.0.1", "port": DEFAULT_PORT, "token": secrets.token_hex(32)}
        try:
            with path.open("x", encoding="utf-8") as f:
                json.dump(cfg, f)
            if os.name != "nt":
                path.chmod(0o600)
        except FileExistsError:
            pass
    return read_settings()


def read_packet(stream):
    line = stream.readline(MAX_BYTES + 1)
    if not line or len(line) > MAX_BYTES or not line.endswith(b"\n"):
        raise ValueError("Empty, incomplete or oversized Maya MCP packet")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Maya MCP packet must be an object")
    return value


def encode_packet(value):
    data = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
    if len(data) > MAX_BYTES:
        raise ValueError("Maya MCP response exceeds 16 MB; request less data")
    return data


def request(method, params=None, timeout=120):
    cfg = read_settings()
    request_id = uuid.uuid4().hex
    payload = {"id": request_id, "token": cfg["token"], "method": method,
               "params": params or {}, "timeout": timeout}
    try:
        with socket.create_connection((cfg["host"], cfg["port"]), timeout=3) as sock:
            sock.settimeout(timeout + 5)
            sock.sendall(encode_packet(payload))
            with sock.makefile("rb") as stream:
                result = read_packet(stream)
    except ConnectionRefusedError as exc:
        raise RuntimeError("Maya MCP 未连接。请打开 Maya，点击 MayaMCP 工具架的 Start 按钮，或拖入 install_maya_mcp.mel。") from exc
    except (socket.timeout, ConnectionResetError) as exc:
        raise RuntimeError("Maya MCP 连接超时或中断，操作结果未知。先查询场景，不要自动重试修改命令。") from exc
    if result.get("id") != request_id:
        raise RuntimeError("Maya MCP response ID mismatch")
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Maya bridge error"))
    return result.get("data")
