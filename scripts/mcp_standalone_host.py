"""Integration-test host: separate Maya standalone scene, never the user's GUI."""
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds
cmds.undoInfo(state=True)
from maya_mcp.bridge import start, stop

bridge = start(use_qt=False)
stop_path = Path(os.environ["MAYA_MCP_TEST_STOP"])
try:
    until = time.monotonic() + 300
    while not stop_path.exists() and time.monotonic() < until:
        bridge.drain()
        time.sleep(.01)
finally:
    stop()
    maya.standalone.uninitialize()
