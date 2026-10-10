"""Run this file from 3ds Max's embedded Python editor or MAXScript."""
import sys
import os
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from max_mcp import max_adapter, bridge, biped_retarget, biped_keys
importlib.reload(biped_keys)
importlib.reload(biped_retarget)
importlib.reload(max_adapter)

port = int(os.environ.get("MAX_MCP_PORT", "8766"))
result = bridge.start(port=port, token=os.environ.get("MAX_MCP_TOKEN", "max-mcp-local"))
result.dispatch = lambda method, params: max_adapter.dispatch(method, params)
print("Max MCP ready: 127.0.0.1:{}".format(port))
