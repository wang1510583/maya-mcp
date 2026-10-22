"""Temporary native constraints on independent arm/foot input frames.

Never constrain a live/zero display surface: its parent inverse reads the solve.
Original channels, animation, DAG parenting and display connections are retained.
"""
import json
import math

VERSION = '1.2.0'
LINK = 'externalConstraint'
DATA = 'externalConstraintData'


def _node(name):
    import maya.cmds as c
    found = c.ls(name, long=True) or []
    if len(found) != 1 or c.nodeType(found[0]) not in ('transform', 'joint'):
        raise ValueError('请选择唯一的物体、定位器、骨骼或控制器：' + str(name))
    if len(c.ls(found[0], long=True, allPaths=True)) != 1:
        raise ValueError('暂不支持实例物体：' + found[0])
    return found[0]


def _same(a, b):
    import maya.cmds as c
    return c.ls(a, uuid=True) == c.ls(b, uuid=True)


def resolve(control):
    """Resolve arm FK, elbow pole and wrist/ankle surfaces to solver inputs."""
    import maya.cmds as c
    control = _node(control)
    for root in c.ls('::*.integratedRigData', objectsOnly=True) or []:
        rig = json.loads(c.getAttr(root + '.integratedRigData'))
        for key, part in rig['parts'].items():
            roles = ('shoulder_fk', 'middle_fk', 'end_fk', 'pole_locator') if key.startswith('arm_') else ('foot',) if key.startswith('leg_') else ()
            role = next((role for role in roles if any(
                n and c.objExists(n) and _same(n, control)
                for n in [part.get(field, {}).get(role) for field in ('controls', 'live_controls', 'zero_controls')]
            )), None)
            if role is None:
                continue
            source = part['controls'][role]
            mode = {'shoulder_fk':'大臂 FK','middle_fk':'小臂 FK','end_fk':'FK',
                    'pole_locator':'肘部 FK','foot':'脚腕'}[role]
            if role in ('end_fk', 'pole_locator'):
                if c.objExists(part['root'] + '.armWorldIKData'):
                    from . import arm_ik
                    ik = arm_ik._data(part['root'])
                    if arm_ik._mode(c.getAttr(ik['global_plug'])):
                        source = ik['controls']['pole' if role == 'pole_locator' else 'wrist']
                        mode = '肘部 IK' if role == 'pole_locator' else 'IK'
            visible = part.get('zero_controls', {}).get(role) or part.get('live_controls', {}).get(role) or control
            return dict(control=_node(visible), source=_node(source), root=part['root'],
                        joints=part.get('joints', []), mode=mode, role=role, namespace=part['namespace'])
    raise ValueError('请选择集成角色绑定的大臂、小臂、肘部、手腕或脚腕控制器。')


def _link(registry, attr):
    import maya.cmds as c
    nodes = c.listConnections(registry + '.' + attr, source=True, destination=False) or []
    return nodes[0] if nodes else None


def registry(node):
    import maya.cmds as c
    if c.objExists(node + '.' + DATA):
        return node
    if c.objExists(node + '.' + LINK):
        nodes = c.listConnections(node + '.' + LINK, source=True, destination=False) or []
        if nodes:
            return nodes[0]
    for candidate in c.listConnections(node + '.message', source=False, destination=True, type='network') or []:
        if c.objExists(candidate + '.' + DATA) and any(
                linked and _same(linked, node) for linked in
                (_link(candidate, 'source'), _link(candidate, 'constraint'))):
            return candidate
    return None


def attach(control, target, kind='parent', options=None, native=False):
    """Bind an arm/foot input (maintain offset by default).

    Playback needs only Maya native nodes, with no per-frame callback. Removing
    through remove() restores the exact original input matrix and animation.
    """
    import maya.cmds as c
    import maya.api.OpenMaya as om
    if kind not in ('parent', 'point', 'orient'):
        raise ValueError('约束类型必须为 parent、point 或 orient。')
    item = resolve(control)
    targets = [_node(n) for n in (target if isinstance(target, (list, tuple)) else [target])]
    if not targets:
        raise ValueError('请选择外部约束目标。')
    control, source, target = item['control'], item['source'], targets[0]
    options = dict(options or {'maintainOffset': True})
    if registry(control):
        raise ValueError('此控制器已有外部约束，请先移除再更换目标。')
    if any(_same(n, control) or _same(n, source) for n in targets):
        raise ValueError('不能让控制器约束自身。')
    if any(_same(n, joint) for n in targets for joint in item['joints']):
        raise ValueError('同一肢体的求解骨骼不能作为外部目标，可能形成循环。')
    for n in (control, source):
        if c.referenceQuery(n, isNodeReferenced=True) or any(c.lockNode(n, q=True, lock=True)):
            raise ValueError('不能修改引用或锁定的绑定输入：' + n)
    dst = source + '.offsetParentMatrix'
    if c.getAttr(dst, lock=True):
        raise ValueError('绑定输入矩阵已锁定：' + source)
    old_edge, old_value = c.connectionInfo(dst, sourceFromDestination=True), c.getAttr(dst)
    parent = (c.listRelatives(source, parent=True, fullPath=True) or [None])[0]
    if not c.getAttr(source + '.inheritsTransform'):
        parent = None
    parent_world = om.MMatrix(c.xform(parent, q=True, ws=True, m=True)) if parent else om.MMatrix()
    from .live_edit import _frame
    anchor_world = _frame(control if native else source)
    poses = {n: c.xform(n, q=True, ws=True, m=True) for n in item['joints'] + [source, control]}
    cycles = set(c.cycleCheck(all=True, list=True) or [])
    selected, auto = c.ls(sl=True, long=True) or [], c.autoKeyframe(q=True, state=True)
    created, linked = [], False
    c.undoInfo(openChunk=True, chunkName='AttachExternalHandFootConstraint')
    c.autoKeyframe(state=False)
    try:
        def create(kind, label, **kwargs):
            n = c.createNode(kind, name=item['namespace'] + ':external_' + label, skipSelect=True, **kwargs)
            created.append(n)
            return n
        anchor = create('transform', 'anchor', parent=item['root'])
        c.setAttr(anchor + '.inheritsTransform', False)
        c.xform(anchor, ws=True, matrix=list(anchor_world))
        c.setAttr(anchor + '.visibility', False)
        command = {'parent': c.parentConstraint, 'point': c.pointConstraint, 'orient': c.orientConstraint}[kind]
        constraint = command(*(targets + [anchor]), name=item['namespace'] + ':external_' + kind, **options)[0]
        created.append(constraint)
        if native:
            # Keep the real constraint visible below the selected controller in
            # the Outliner. Its inputs still read the independent anchor.
            constraint = c.parent(constraint, control, relative=True)[0]
            created[-1] = constraint
        matrix = create('multMatrix', 'inputFrame')
        if old_edge:
            c.connectAttr(old_edge, matrix + '.matrixIn[0]')
        else:
            c.setAttr(matrix + '.matrixIn[0]', *old_value, type='matrix')
        c.setAttr(matrix + '.matrixIn[1]', *list(parent_world * anchor_world.inverse()), type='matrix')
        c.connectAttr(anchor + '.worldMatrix[0]', matrix + '.matrixIn[2]')
        if parent:
            # Read the actual DAG parent's inverse, never source.parentInverseMatrix
            # (which includes this very offsetParentMatrix in Maya).
            c.connectAttr(parent + '.worldInverseMatrix[0]', matrix + '.matrixIn[3]')
        c.connectAttr(matrix + '.matrixSum', dst, force=True)
        if set(c.cycleCheck(all=True, list=True) or []) - cycles:
            raise ValueError('目标物体依赖这个肢体的输出，会形成循环；已撤回此次约束。')
        error = max([abs(a-b) for n, pose in poses.items() for a,b in zip(pose, c.xform(n,q=True,ws=True,m=True))] + [0])
        if not math.isfinite(error) or (options.get('maintainOffset', False) and error > 1e-4):
            raise RuntimeError('外部约束改变了添加时的姿态，已撤回：' + str(error))
        owner = create('network', 'constraintData')
        for attr, node in dict(control=control, source=source, target=target, anchor=anchor,
                               constraint=constraint, matrix=matrix).items():
            c.addAttr(owner, longName=attr, attributeType='message')
            c.connectAttr(node + '.message', owner + '.' + attr)
        c.addAttr(owner, longName=DATA, dataType='string')
        c.setAttr(owner + '.' + DATA, json.dumps(dict(version=VERSION, kind=kind, mode=item['mode'],
                  original_matrix=old_value, native=native)), type='string', lock=True)
        if not c.objExists(control + '.' + LINK):
            c.addAttr(control, longName=LINK, attributeType='message'); linked = True
        c.connectAttr(owner + '.message', control + '.' + LINK)
        if native:
            from . import native_constraints
            native_constraints.watch(constraint)
        return dict(registry=owner, constraint=constraint, mode=item['mode'], max_pose_error=error)
    except Exception:
        current = c.connectionInfo(dst, sourceFromDestination=True)
        if current and current != old_edge:
            c.disconnectAttr(current, dst)
        if old_edge:
            if not c.isConnected(old_edge, dst):
                c.connectAttr(old_edge, dst, force=True)
        else:
            c.setAttr(dst, *old_value, type='matrix')
        if linked:
            c.deleteAttr(control + '.' + LINK)
        for n in reversed(created):
            if c.objExists(n):
                c.delete(n)
        raise
    finally:
        c.autoKeyframe(state=auto)
        c.select(selected, replace=True) if selected else c.select(clear=True)
        c.undoInfo(closeChunk=True)


def remove(node):
    """Remove only this temporary layer; restore pre-constraint animation/space."""
    import maya.cmds as c
    owner = registry(node)
    if not owner:
        raise ValueError('所选控制器没有本工具创建的外部约束。')
    source, control, matrix = (_link(owner, a) for a in ('source', 'control', 'matrix'))
    if not all((source, control, matrix)):
        raise ValueError('外部约束登记不完整，请先撤销手动删除的输入节点。')
    dst = source + '.offsetParentMatrix'
    if not c.isConnected(matrix + '.matrixSum', dst) or c.getAttr(dst, lock=True):
        raise ValueError('约束输入连接已经被其他操作修改，未覆盖。')
    original = c.connectionInfo(matrix + '.matrixIn[0]', sourceFromDestination=True)
    value = c.getAttr(matrix + '.matrixIn[0]')
    nodes = [_link(owner, a) for a in ('constraint', 'anchor')] + [matrix, owner]
    for n in [control, source] + [n for n in nodes if n]:
        if c.referenceQuery(n, isNodeReferenced=True) or any(c.lockNode(n, q=True, lock=True)):
            raise ValueError('临时约束节点被引用或锁定，未移除：' + n)
    if c.getAttr(control + '.' + LINK, lock=True):
        raise ValueError('外部约束登记已锁定，未移除。')
    anchor = _link(owner, 'anchor')
    if anchor and any(c.nodeType(n) in ('transform', 'joint') for n in c.listRelatives(anchor, children=True) or []):
        raise ValueError('临时约束空间下新增了物体，未删除；请先移出这些物体。')
    selected, auto = c.ls(sl=True, long=True) or [], c.autoKeyframe(q=True, state=True)
    c.undoInfo(openChunk=True, chunkName='RemoveExternalHandFootConstraint'); c.autoKeyframe(state=False)
    try:
        c.disconnectAttr(matrix + '.matrixSum', dst)
        if original:
            c.connectAttr(original, dst)
        else:
            c.setAttr(dst, *value, type='matrix')
        c.deleteAttr(control + '.' + LINK)
        for n in nodes:
            if n and c.objExists(n):
                c.delete(n)
        return dict(removed=True, control=control)
    finally:
        c.autoKeyframe(state=auto)
        remaining = [n for n in selected if c.objExists(n)]
        c.select(remaining, replace=True) if remaining else c.select(clear=True)
        c.undoInfo(closeChunk=True)
