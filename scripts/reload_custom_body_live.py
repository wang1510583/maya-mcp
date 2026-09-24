"""Reload only the custom rig modules and registration in interactive Maya."""
import importlib

for name in ("topology", "definition", "targets", "fitting", "context", "nodes", "controls", "skeleton",
             "drivers", "display", "builder"):
    importlib.reload(importlib.import_module("maya_agent.rigs.custom_body." + name))
importlib.reload(importlib.import_module("maya_agent.rigs.custom_body"))
importlib.reload(importlib.import_module("maya_agent.tools.custom_body_rig"))
from maya_agent.tools.registry import get_tool
result = {"parameters": get_tool("create_custom_body_rig").parameters}
