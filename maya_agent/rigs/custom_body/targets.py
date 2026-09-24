"""Ordered target inspection and reversible output constraints, independent of UI."""
import math

CHANNELS = tuple(channel + axis for channel in ('translate', 'rotate') for axis in 'XYZ')


def ordered_selection():
    import maya.cmds as c
    if not c.selectPref(query=True, trackSelectionOrder=True):
        raise ValueError('请先打开自定义身体绑定窗口，再从腰部到胸部重新逐个选择物体。')
    return c.ls(orderedSelection=True, long=True) or []


def inspect(names):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    if not isinstance(names, (list, tuple)) or not 2 <= len(names) <= 64:
        raise ValueError('选择模式需要 2–64 个物体；列表第一项是腰部，最后一项是胸部。')
    samples, seen = [], set()
    for name in names:
        if not isinstance(name, str) or '.' in name:
            raise ValueError('请选物体或骨骼，不要选择顶点等组件。')
        matches = c.ls(name, long=True) or []
        if len(matches) != 1 or c.nodeType(matches[0]) not in ('transform', 'joint'):
            raise ValueError('目标不存在、重名或不是 transform / joint：' + name)
        node = matches[0]
        if node in seen:
            raise ValueError('目标列表有重复物体：' + node)
        seen.add(node)
        if c.referenceQuery(node, isNodeReferenced=True) or any(c.lockNode(node, query=True, lock=True)):
            raise ValueError('目标属于引用或节点已锁定，未改动场景：' + node)
        selection = om.MSelectionList()
        selection.add(node)
        if om.MFnDagNode(selection.getDagPath(0)).isInstanced():
            raise ValueError('暂不支持实例化的目标：' + node)
        for channel in CHANNELS:
            plug = node + '.' + channel
            # Maya reports animated channels as settable; check each incoming plug explicitly.
            if (c.getAttr(plug, lock=True) or not c.getAttr(plug, settable=True)
                    or c.listConnections(plug, source=True, destination=False)):
                raise ValueError('目标通道已锁定或已有动画/连接，未覆盖：' + plug)
        ancestor = node
        while ancestor:
            for attr in ('translate', 'rotate', 'offsetParentMatrix') + CHANNELS:
                if c.listConnections(ancestor + '.' + attr, source=True, destination=False):
                    raise ValueError('目标或父级已有动画/驱动连接，未覆盖：' + ancestor + '.' + attr)
            parent = c.listRelatives(ancestor, parent=True, fullPath=True) or []
            ancestor = parent[0] if parent else None
        matrix = om.MMatrix(c.xform(node, query=True, worldSpace=True, matrix=True))
        tm = om.MTransformationMatrix(matrix)
        # Parent constraints are predictable on rigid / positive uniformly scaled frames.
        scale, shear = tm.scale(om.MSpace.kWorld), tm.shear(om.MSpace.kWorld)
        if min(scale) <= 0 or max(scale)-min(scale) > 1e-5 or any(abs(v) > 1e-5 for v in shear):
            raise ValueError('目标世界变换存在非均匀/负缩放或剪切，请先整理：' + node)
        rotation = tm.rotation(asQuaternion=True)
        euler = rotation.asEulerRotation()
        position = c.xform(node, query=True, worldSpace=True, translation=True)
        if not all(math.isfinite(v) for v in position + list(matrix)):
            raise ValueError('目标变换不是有限数值：' + node)
        samples.append({'node': node, 'position': position,
                        'rotation': [math.degrees(v) for v in (euler.x, euler.y, euler.z)],
                        'matrix': list(rotation.asMatrix()), 'world_matrix': list(matrix),
                        'channels': {attr: c.getAttr(node + '.' + attr) for attr in CHANNELS}})
    lengths = [math.dist(a['position'], b['position']) for a, b in zip(samples, samples[1:])]
    if any(length < 1e-5 for length in lengths):
        raise ValueError('相邻目标位置重合，无法确定骨骼长度；请调整选择顺序或目标位置。')
    return samples, sum(lengths)


def connect(ctx, samples):
    import json
    c = ctx.cmds
    mappings = []
    root = ctx.namespace + ':hips_zero'
    c.addAttr(root, longName='customBodyTargets', dataType='string')
    c.setAttr(root + '.customBodyTargets', json.dumps([s['node'] for s in samples]), type='string', lock=True)
    for index, (sample, joint, ctrl) in enumerate(zip(samples, ctx.definition['joints'], ctx.definition['controls'].values()), 1):
        driver = ctx.namespace + ':' + joint
        requested = ctx.namespace + ':target{:02d}_parentConstraint'.format(index)
        try:
            constraint = c.parentConstraint(driver, sample['node'], maintainOffset=True, name=requested)[0]
        finally:
            if c.objExists(requested):
                ctx.created.append(requested)
        mappings.append({'target': sample['node'], 'joint': driver,
                         'control': ctx.namespace + ':' + ctrl, 'constraint': constraint})
    # Any unexpected target movement aborts and rolls back, including bind-pose drift.
    for sample in samples:
        actual = c.xform(sample['node'], query=True, worldSpace=True, matrix=True)
        if max(abs(a-b) for a, b in zip(actual, sample['world_matrix'])) > 1e-5:
            raise RuntimeError('创建约束时目标姿态发生变化，已取消：' + sample['node'])
    return mappings


def restore(samples):
    import maya.cmds as c
    for sample in samples:
        if c.objExists(sample['node']):
            for attr, value in sample['channels'].items():
                c.setAttr(sample['node'] + '.' + attr, value)
