"""Max-side scene and Biped operations. Imported only inside 3ds Max."""
import math
from pathlib import Path

from pymxs import runtime as rt, attime


def _scene_path():
    """Max exposes these as separate MAXScript globals, not one Python property."""
    try:
        path = str(rt.maxFilePath)
        name = str(rt.maxFileName)
        return path + name
    except Exception:
        return ""


def _node(name):
    if not name:
        raise ValueError("An object name is required")
    found = rt.getNodeByName(name)
    if found is None:
        raise ValueError("Max object not found: " + str(name))
    return found


def _matrix(node):
    return [[float(v) for v in (row.x, row.y, row.z)]
            for row in (node.transform.row1, node.transform.row2,
                        node.transform.row3, node.transform.row4)]


def _samples(root, start, end, step, bones, extra_frames=None):
    root_node = _node(root)
    if not all(math.isfinite(v) for v in (start, end, step)) or end < start or step <= 0:
        raise ValueError("Invalid sample range")
    def descendants(node):
        yield node
        for child in node.children:
            yield from descendants(child)
    hierarchy = list(descendants(root_node))
    allowed = {int(rt.getHandleByAnim(n)) for n in hierarchy}
    nodes = [_node(name) for name in bones] if bones else [
        n for n in hierarchy if str(rt.classOf(n)) == "Biped_Object"]
    if not nodes:
        raise ValueError("No Biped bones found under root")
    if any(int(rt.getHandleByAnim(n)) not in allowed for n in nodes):
        raise ValueError("Requested bone is outside the specified root")
    frames = []
    f = float(start)
    while f <= float(end) + 1e-8:
        frames.append(f)
        f += float(step)
        if len(frames) > 10001:
            raise ValueError("At most 10001 samples are allowed")
    if frames[-1]<float(end)-1e-8:
        frames.append(float(end))
        if len(frames)>10001:raise ValueError("At most 10001 samples are allowed")
    if extra_frames:
        frames=sorted(set(frames)|{float(f) for f in extra_frames if start<=float(f)<=end})
        if len(frames)>10001 or not all(math.isfinite(f) for f in frames):
            raise ValueError('Invalid key-time sampling range')
    out = []
    for frame in frames:
        with attime(frame):
            out.append({"frame": frame, "bones": {str(n.name): _matrix(n) for n in nodes}})
    return {"root": str(root_node.name), "samples": out, "fps": int(rt.frameRate),
            "up_axis": "Z", "matrix_layout": "row_vectors_4x3_translation_last",
            "system_unit": str(rt.units.SystemType), "system_scale": float(rt.units.SystemScale),
            "parents": {str(n.name): str(n.parent.name) if n.parent else None for n in nodes}}


def dispatch(method, params):
    if method == "retarget_biped":
        from .biped_retarget import capture
        return capture(params)
    if method == "capture_biped":
        from .biped_keys import collect
        root=_node(params['root'])
        start=float(params.get('start',float(rt.animationRange.start)))
        end=float(params.get('end',float(rt.animationRange.end)))
        step=float(params.get('step',1.0))
        old=bool(root.controller.figureMode)
        if old:raise ValueError('Exit Biped Figure Mode before capturing animation')
        data=_samples(params['root'],start,end,step,params.get('bones') or [])
        keys=collect(root,[_node(n) for n in data['samples'][0]['bones'] if n!=str(root.name) and not n.endswith(' Footsteps')])
        data=_samples(params['root'],start,end,step,params.get('bones') or [],keys['times'])
        data['source_keys']=keys
        try:
            root.controller.figureMode=True
            data['reference']=_samples(params['root'],start,start,1,params.get('bones') or [])['samples'][0]['bones']
        finally:root.controller.figureMode=old
        data['format']='max_biped_motion_v1'
        return data
    if method == "status":
        return {"application": "3ds Max", "version": str(rt.maxVersion()),
                "scene": _scene_path(), "bridge": "ready"}
    if method == "scene":
        limit = max(1, min(int(params.get("limit", 100)), 1000))
        selected = [str(n.name) for n in rt.selection]
        top = [str(n.name) for n in rt.objects if n.parent is None][:limit]
        return {"scene": _scene_path(), "time": float(rt.sliderTime),
                "range": [float(rt.animationRange.start), float(rt.animationRange.end)],
                "fps": int(rt.frameRate), "object_count": len(rt.objects),
                "selection": selected, "top_level": top,
                "objects": [{"name": str(n.name), "class": str(rt.classOf(n)),
                             "parent": str(n.parent.name) if n.parent else None}
                            for n in list(rt.objects)[:limit]]}
    if method == "maxscript":
        code = params.get("code", "")
        if not isinstance(code, str) or len(code) > 1_000_000:
            raise ValueError("MAXScript must be a string under 1 MB")
        value = rt.execute(code)
        return {"result": str(value) if value is not None else None}
    if method == "python":
        code = params.get("code", "")
        if not isinstance(code, str) or len(code) > 1_000_000:
            raise ValueError("Python must be a string under 1 MB")
        scope = {"rt": rt, "pymxs": __import__("pymxs")}
        exec(compile(code, "<max_mcp>", "exec"), scope, scope)
        return {"result": scope.get("result")}
    if method == "export_bip":
        root = _node(params["root"]); path = str(Path(params["file_path"]).resolve())
        if not path.lower().endswith(".bip"): raise ValueError("file_path must end in .bip")
        if Path(path).exists() and not params.get("overwrite", False):
            raise ValueError("File already exists; use overwrite=True explicitly")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        rt.biped.saveBipFile(root.controller, path)
        return {"root": str(root.name), "file_path": path, "bytes": Path(path).stat().st_size}
    if method == "load_bip":
        root = _node(params["root"]); path = str(Path(params["file_path"]).resolve())
        if not Path(path).is_file(): raise ValueError("BIP file not found: " + path)
        rt.biped.loadBipFile(root.controller, path)
        return {"root": str(root.name), "file_path": path, "loaded": True}
    if method == "sample_biped":
        return _samples(params["root"], float(params["start"]), float(params["end"]),
                        float(params.get("step", 1.0)), params.get("bones") or [])
    raise ValueError("Unknown Max MCP method: " + str(method))
