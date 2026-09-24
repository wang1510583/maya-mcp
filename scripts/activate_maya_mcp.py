"""Fresh drag-drop entry point: stop, reload, restart and record non-secret diagnostics."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fingerprint(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


report = {"timestamp": datetime.now().isoformat(), "pid": os.getpid()}
old_bridge = sys.modules.get("maya_mcp.bridge")
old_connection = sys.modules.get("maya_mcp.connection")
if old_connection:
    report["previous_config_path"] = str(old_connection.settings_path())
if old_bridge:
    active = getattr(old_bridge, "_active", None)
    if active:
        report["previous_token_fingerprint"] = fingerprint(active.config.get("token"))
    old_bridge.stop()

importlib.invalidate_caches()
for name in ("maya_mcp.connection", "maya_mcp.maya_adapter", "maya_mcp.bridge", "maya_mcp.install"):
    if name in sys.modules:
        importlib.reload(sys.modules[name])

from maya_mcp.install import install_in_maya
from maya_mcp.connection import settings_path
from maya_mcp import bridge

try:
    install_in_maya()
    cfg = bridge._active.config
    report.update(started=True, config_path=str(settings_path()),
                  token_fingerprint=fingerprint(cfg["token"]),
                  host=cfg["host"], port=cfg["port"],
                  bridge_file=bridge.__file__, python=sys.version)
except Exception as exc:
    report.update(started=False, error=repr(exc))
    raise
finally:
    output = ROOT / "outputs" / "mcp-runtime.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[Maya MCP] Diagnostics:", str(output))
