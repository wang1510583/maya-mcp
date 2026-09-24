"""Maya-side operations. Imported only inside Maya / mayapy."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile


def prepare():
    import maya.cmds  # noqa: F401
    # Pure Python PyYAML is vendored by the installer, not installed into Maya.
    import sys
    deps = str(Path(__file__).resolve().parents[1] / ".maya-mcp-deps")
    if deps not in sys.path:
        sys.path.append(deps)
    from maya_agent.tools.registry import ensure_tools_loaded
    ensure_tools_loaded()


def dispatch(method, params):
    import maya.cmds as cmds
    from maya_agent.tools.registry import all_tools, get_tool, run_tool
    if method == "status":
        return {"connected": True, "maya_version": cmds.about(version=True),
                "pid": os.getpid(), "batch": cmds.about(batch=True),
                "scene": cmds.file(query=True, sceneName=True),
                "modified": cmds.file(query=True, modified=True), "bridge_version": "0.1.0",
                "tool_count": len(all_tools())}
    if method == "scene":
        limit = max(1, min(int(params.get("limit", 100)), 1000))
        nodes = cmds.ls(assemblies=True, long=True) or []
        return {"scene": cmds.file(query=True, sceneName=True),
                "modified": cmds.file(query=True, modified=True),
                "selection": cmds.ls(selection=True, long=True) or [],
                "current_frame": cmds.currentTime(query=True),
                "playback_range": [cmds.playbackOptions(query=True, minTime=True), cmds.playbackOptions(query=True, maxTime=True)],
                "time_unit": cmds.currentUnit(query=True, time=True),
                "cameras": cmds.ls(type="camera", long=True) or [],
                "root_count": len(nodes), "roots": nodes[:limit]}
    if method == "object":
        matches = cmds.ls(params["name"], long=True) or []
        if len(matches) != 1:
            raise ValueError("Object missing or ambiguous; use a full DAG path")
        node = matches[0]
        info = {"name": node, "type": cmds.nodeType(node),
                "parent": cmds.listRelatives(node, parent=True, fullPath=True) or [],
                "children": cmds.listRelatives(node, children=True, fullPath=True) or []}
        if cmds.objectType(node, isAType="transform"):
            info.update(translation=cmds.xform(node, query=True, worldSpace=True, translation=True),
                        rotation=cmds.xform(node, query=True, worldSpace=True, rotation=True),
                        scale=cmds.xform(node, query=True, relative=True, scale=True))
        return info
    if method == "list_tools":
        query = str(params.get("query", "")).lower()
        category = params.get("category", "")
        return [{"name": t.name, "display_name": getattr(t, "display_name", ""), "description": t.description, "category": t.category,
                 "parameters": t.parameters, "destructive": t.destructive}
                for t in all_tools() if (not category or t.category == category)
                and (not query or query in (t.name + t.description).lower())]
    if method == "call_tool":
        name = params["name"]
        if get_tool(name) is None:
            raise ValueError("Unknown Maya tool: " + name)
        args = params.get("arguments", {})
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        with undo_chunk("MayaMCP_" + name):
            result = run_tool(name, args)
        data = json.loads(result.to_str())
        data["images"] = [img.to_dict() for img in (result.images or [])]
        return data
    if method == "python":
        output, errors = io.StringIO(), io.StringIO()
        namespace = {"cmds": cmds, "__name__": "__maya_mcp__"}
        # Exceptions propagate once; never retry on a worker thread.
        with undo_chunk("MayaMCP_Python"), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            exec(compile(params["code"], "<maya_mcp>", "exec"), namespace, namespace)
        return {"result": namespace.get("result"), "stdout": output.getvalue(), "stderr": errors.getvalue()}
    if method == "mel":
        import maya.mel
        with undo_chunk("MayaMCP_MEL"):
            return {"result": maya.mel.eval(params["code"])}
    if method == "screenshot":
        import maya.OpenMaya as om
        import maya.OpenMayaUI as omui
        if cmds.about(batch=True):
            raise RuntimeError("Viewport screenshot requires interactive Maya")
        size = max(128, min(int(params.get("max_size", 1280)), 2048))
        view = omui.M3dView.active3dView()
        view.refresh(False, True)
        img = om.MImage()
        view.readColorBuffer(img, True)
        # API 1.0 dimensions use unsigned-int pointers.
        wu, hu = om.MScriptUtil(), om.MScriptUtil()
        wu.createFromInt(0)
        hu.createFromInt(0)
        wp, hp = wu.asUintPtr(), hu.asUintPtr()
        img.getSize(wp, hp)
        width, height = om.MScriptUtil.getUint(wp), om.MScriptUtil.getUint(hp)
        factor = min(1.0, float(size) / max(width, height, 1))
        if factor < 1:
            img.resize(max(1, int(width * factor)), max(1, int(height * factor)), False)
        with tempfile.TemporaryDirectory(prefix="maya_mcp_") as directory:
            path = str(Path(directory) / "viewport.png")
            img.writeToFile(path, "png")
            return {"mime": "image/png", "data_b64": base64.b64encode(Path(path).read_bytes()).decode("ascii")}
    if method == "undo":
        expected = params["expected_chunk"]
        if not expected.startswith("MayaMCP_"):
            raise ValueError("Only MayaMCP_ chunks may be undone by this tool")
        current = cmds.undoInfo(query=True, undoName=True)
        if current != expected:
            raise ValueError("Undo head is {!r}; refusing to undo unrelated work".format(current))
        cmds.undo()
        return {"undone": expected}
    raise ValueError("Unknown bridge method: " + str(method))


@contextlib.contextmanager
def undo_chunk(name):
    import maya.cmds as cmds
    enabled = cmds.undoInfo(query=True, state=True)
    if enabled:
        cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        if enabled:
            cmds.undoInfo(closeChunk=True)
