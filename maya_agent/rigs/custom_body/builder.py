"""Versioned public build pipeline; safe repetition, rollback and one Maya undo chunk."""
from . import controls, display, drivers, skeleton
from .context import BuildContext
from .definition import DISPLAY_NAME, VERSION, load_definition, validate_options
from .nodes import restore_channel_flags, restore_values

COMPONENTS = (controls.build, skeleton.build, drivers.build, display.build)


def build(namespace="customBody", on_conflict="increment", segment_count=4, height=6.0,
          use_selection=False, targets=None, copy_animation=False,
          start_frame=None, end_frame=None, sample_step=1.0):
    validate_options(namespace, on_conflict)
    import maya.cmds as c
    import threading
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("自定义身体绑定必须在 Maya 主线程创建")
    from . import targets as target_tools
    from .animation import Transfer, frame_range
    if copy_animation and not (use_selection or targets is not None):
        raise ValueError('拷贝动画至控制器需要启用选择模式。')
    frames = frame_range(c.playbackOptions(query=True, minTime=True) if start_frame is None else start_frame,
                         c.playbackOptions(query=True, maxTime=True) if end_frame is None else end_frame,
                         sample_step) if copy_animation else []
    samples = []
    if use_selection or targets is not None:
        samples, height = target_tools.inspect(targets if targets is not None else target_tools.ordered_selection(),
                                               allow_animation=copy_animation)
        segment_count = len(samples)
    data = load_definition(segment_count, height, preserve_four=not bool(samples))
    if samples:
        from .fitting import fit_definition
        data = fit_definition(data, samples)
    if c.currentUnit(query=True, linear=True) != data["linear_unit"]:
        raise ValueError("当前版本模板以厘米为单位；请在厘米场景中创建")
    if c.currentUnit(query=True, angle=True) != 'deg':
        raise ValueError("请使用角度单位 deg 的场景创建绑定")
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
    transfer = Transfer(ctx, samples, frames) if copy_animation else None
    use_undo = c.undoInfo(query=True, state=True)
    if use_undo:
        c.undoInfo(openChunk=True, chunkName="MayaMCP_create_custom_body_rig")
    try:
        c.namespace(setNamespace=":")
        c.namespace(add=namespace)
        if transfer:
            transfer.capture()
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
        if transfer:
            transfer.detach()
        mappings = target_tools.connect(ctx, samples) if samples else []
        animation_report = transfer.bake(mappings) if transfer else None
        result = {"display_name": DISPLAY_NAME, "version": VERSION, "namespace": namespace,
                  "segment_count": segment_count, "height": float(height),
                  "mode": "selection" if samples else "standard", "target_mapping": mappings,
                  "animation_transfer": animation_report,
                  "nodes": list(ctx.created), "node_count": len(ctx.created),
                  "connection_count": len(data["connections"]),
                  "controls": {role: namespace + ":" + name for role, name in data["controls"].items()},
                  "joints": [namespace + ":" + name for name in data["joints"]],
                  "display_layer_connections": ctx.layer_connections}
    except Exception:
        if transfer:
            transfer.release_backup()
        ctx.cleanup()
        if transfer:
            transfer.rollback()
        elif samples:
            target_tools.restore(samples)
        raise
    finally:
        if transfer:
            c.currentTime(transfer.time, edit=True)
        c.namespace(setNamespace=previous_namespace)
        if selection:
            c.select(selection, replace=True)
        else:
            c.select(clear=True)
        if use_undo:
            c.undoInfo(closeChunk=True)
    return result
