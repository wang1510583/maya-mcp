"""Versioned public build pipeline; safe repetition, rollback and one Maya undo chunk."""
from . import controls, display, drivers, skeleton
from .context import BuildContext
from .definition import DISPLAY_NAME, VERSION, load_definition, validate_options
from .nodes import restore_channel_flags, restore_values

COMPONENTS = (controls.build, skeleton.build, drivers.build, display.build)


def build(namespace="customBody", on_conflict="increment", segment_count=4, height=6.0):
    validate_options(namespace, on_conflict)
    data = load_definition(segment_count, height)
    import maya.cmds as c
    import threading
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("自定义身体绑定必须在 Maya 主线程创建")
    if c.currentUnit(query=True, linear=True) != data["linear_unit"]:
        raise ValueError("当前版本模板以厘米为单位；请在厘米场景中创建")
    base = namespace
    number = 2
    while c.namespace(exists=":" + namespace):
        if on_conflict == "error":
            raise ValueError("命名空间已存在，未修改场景：" + namespace)
        namespace = "{}_{:02d}".format(base, number)
        number += 1
    previous_namespace = c.namespaceInfo(currentNamespace=True)
    selection = c.ls(selection=True, long=True) or []
    ctx = BuildContext(c, data, namespace)
    use_undo = c.undoInfo(query=True, state=True)
    if use_undo:
        c.undoInfo(openChunk=True, chunkName="MayaMCP_create_custom_body_rig")
    try:
        c.namespace(setNamespace=":")
        c.namespace(add=namespace)
        for component in COMPONENTS:
            component(ctx)
        restore_values(ctx)
        drivers.connect(ctx)
        restore_channel_flags(ctx)
        root = namespace + ":hips_zero"
        for attr, value in (("customBodyRigName", DISPLAY_NAME), ("customBodyRigVersion", VERSION)):
            c.addAttr(root, longName=attr, dataType="string")
            c.setAttr(root + "." + attr, value, type="string", lock=True)
        for attr, kind, value in (("customBodySegmentCount", "long", segment_count),
                                  ("customBodyHeight", "double", height)):
            c.addAttr(root, longName=attr, attributeType=kind)
            c.setAttr(root + "." + attr, value, lock=True)
        result = {"display_name": DISPLAY_NAME, "version": VERSION, "namespace": namespace,
                  "segment_count": segment_count, "height": float(height),
                  "nodes": list(ctx.created), "node_count": len(ctx.created),
                  "connection_count": len(data["connections"]),
                  "controls": {role: namespace + ":" + name for role, name in data["controls"].items()},
                  "joints": [namespace + ":" + name for name in data["joints"]],
                  "display_layer_connections": ctx.layer_connections}
    except Exception:
        ctx.cleanup()
        raise
    finally:
        c.namespace(setNamespace=previous_namespace)
        if selection:
            c.select(selection, replace=True)
        else:
            c.select(clear=True)
        if use_undo:
            c.undoInfo(closeChunk=True)
    return result
