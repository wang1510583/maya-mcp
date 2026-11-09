"""Euler operations in the solver's rotation space, including zero surfaces.

No constraints or world-space feedback are introduced. Order conversion preserves
poses at the union of existing XYZ rotation key times, without interval sampling.
Between-key interpolation is left to Maya. Maya 2024, degree angle units.
"""
import json
import math
import maya.cmds as cmds
import maya.api.OpenMaya as om

ORDERS = ('xyz', 'yzx', 'zxy', 'xzy', 'yxz', 'zyx')
ATTRS = ('rotateX', 'rotateY', 'rotateZ')


def describe(node, editable=False):
    names = cmds.ls(node, long=True) or []
    if len(names) != 1 or cmds.nodeType(names[0]) not in ('transform', 'joint'):
        raise ValueError('请选择唯一的控制器或变换节点：' + node)
    node = names[0]
    if cmds.currentUnit(q=True, angle=True) != 'deg':
        raise ValueError('请先将 Maya 角度单位设为度。')
    offsets = [0.0] * 3
    source = node
    if cmds.objExists(node + '.zeroChannelData'):
        data = json.loads(cmds.getAttr(node + '.zeroChannelData'))
        source = data['source']
        for i, attr in enumerate(ATTRS):
            if attr not in data['offsets']:
                raise ValueError('此零位控制器没有完整的 XYZ 旋转通道：' + node)
            offsets[i] = data['offsets'][attr]
            edge = cmds.connectionInfo(source + '.' + attr, sfd=True)
            blend = edge.rsplit('.', 1)[0]
            if (not blend or cmds.nodeType(blend) != 'animBlendNodeAdditiveDA'
                    or not cmds.isConnected(node + '.' + attr, blend + '.inputA')
                    or cmds.connectionInfo(blend + '.inputB', sfd=True)
                    or cmds.connectionInfo(blend + '.weightA', sfd=True)
                    or cmds.connectionInfo(blend + '.weightB', sfd=True)
                    or abs(cmds.getAttr(blend + '.inputB') - offsets[i]) > 1e-7
                    or abs(cmds.getAttr(blend + '.weightA') - 1) > 1e-9
                    or abs(cmds.getAttr(blend + '.weightB') - 1) > 1e-9):
                raise ValueError('归零旋转连接已变化，未修改：' + node)
        if not cmds.isConnected(node + '.rotateOrder', source + '.rotateOrder'):
            raise ValueError('归零控制器与输入旋转顺序未连接：' + node)
    curves = []
    times = []
    if editable and (cmds.getAttr(node + '.rotateOrder', lock=True)
                     or cmds.connectionInfo(node + '.rotateOrder', sfd=True)):
        raise ValueError('旋转顺序被锁定或驱动：' + node)
    for attr in ATTRS:
        plug = node + '.' + attr
        edge = cmds.connectionInfo(plug, sfd=True)
        curve = edge.rsplit('.', 1)[0] if edge else None
        if editable:
            if cmds.getAttr(plug, lock=True):
                raise ValueError('旋转通道已锁定：' + plug)
            if curve and cmds.nodeType(curve) != 'animCurveTA':
                raise ValueError('暂不覆盖动画层、约束或表达式驱动：' + plug)
            if curve:
                if not cmds.keyframe(curve, q=True, kc=True):
                    raise ValueError('旋转动画曲线为空：' + curve)
                consumers = cmds.listConnections(curve + '.output', s=False, d=True, p=True) or []
                if len(consumers) != 1 or cmds.lockNode(curve, q=True, lock=True)[0]:
                    raise ValueError('动画曲线共享或锁定，未修改：' + curve)
                # Time warps and cycle/linear infinity need their own conversion.
                driver = cmds.connectionInfo(curve + '.input', sfd=True)
                if driver and cmds.nodeType(driver.split('.')[0]) != 'time':
                    raise ValueError('不支持重映射时间曲线：' + curve)
        curves.append(curve)
        times.append(sorted(set(cmds.keyframe(plug, q=True, tc=True) or [])))
    return dict(node=node, source=source, offsets=offsets, curves=curves,
                times=times, order=cmds.getAttr(node + '.rotateOrder'))


def actual_values(info, frame):
    return [cmds.getAttr(info['node'] + '.' + a, time=frame) + o
            for a, o in zip(ATTRS, info['offsets'])]


def euler(values, order):
    return om.MEulerRotation(*[math.radians(v) for v in values], order)


def rotation_error(a, ao, b, bo):
    qa, qb = euler(a, ao).asQuaternion(), euler(b, bo).asQuaternion()
    dot = abs(qa.x*qb.x + qa.y*qb.y + qa.z*qb.z + qa.w*qb.w)
    return math.degrees(2 * math.acos(min(1.0, dot)))


def tolerances(node, frame):
    info = describe(node)
    original = euler(actual_values(info, frame), info['order'])
    result = []
    for order, label in enumerate(ORDERS):
        converted = om.MEulerRotation(original)
        converted.reorderIt(order)
        middle = math.degrees(converted['xyz'.index(label[1])])
        result.append(abs(((middle + 90) % 180) - 90) / 90)
    return result


def _key_times(info):
    times = sorted(set(t for axis in info['times'] for t in axis))
    if not times:
        return [cmds.currentTime(q=True)]
    return times


def _transaction(infos, operation):
    """Keep curve identities, connections and full backup curves for rollback."""
    if not cmds.undoInfo(q=True, state=True):
        raise ValueError('请先启用 Maya 撤销，以便撤销旋转转换。')
    saved = []
    auto = cmds.autoKeyframe(q=True, state=True)
    cmds.undoInfo(openChunk=True, chunkName='RigAwareEuler')
    try:
        cmds.autoKeyframe(state=False)
        for info in infos:
            row = dict(info=info, values=[cmds.getAttr(info['node']+'.'+a) for a in ATTRS], copies=[])
            saved.append(row)
            for curve in info['curves']:
                row['copies'].append(cmds.duplicate(curve, name='__rigEulerBackup#')[0] if curve else None)
        try:
            return operation()
        except Exception:
            for row in saved:
                info = row['info']
                cmds.setAttr(info['node']+'.rotateOrder', info['order'])
                for attr, curve, backup, value in zip(ATTRS, info['curves'], row['copies'], row['values']):
                    plug = info['node']+'.'+attr
                    if curve:
                        cmds.copyKey(backup)
                        cmds.pasteKey(curve, option='replaceCompletely')
                    else:
                        edge = cmds.connectionInfo(plug, sfd=True)
                        if edge and cmds.nodeType(edge.split('.')[0]) == 'animCurveTA':
                            cmds.delete(edge.split('.')[0])
                        cmds.setAttr(plug, value)
            raise
    finally:
        for row in saved:
            for backup in row['copies']:
                if backup and cmds.objExists(backup):
                    cmds.delete(backup)
        cmds.autoKeyframe(state=auto)
        cmds.undoInfo(closeChunk=True)


def filter_euler(objects=None):
    """Filter full XYZ curves after adding offsets, then subtract offsets."""
    objects = objects or cmds.ls(sl=True, long=True) or []
    if not objects:
        raise ValueError('请选择需要过滤的控制器。')
    infos = [describe(n, editable=True) for n in dict.fromkeys(objects)]
    for info in infos:
        if not all(info['curves']) or not info['times'][0] or not all(t == info['times'][0] for t in info['times']):
            raise ValueError('欧拉过滤要求 XYZ 三轴关键帧时间一致：' + info['node'])
    def apply():
        reports = []
        for info in infos:
            temp = None
            copies = []
            try:
                temp = cmds.createNode('transform', name='__rigEulerFilter#', skipSelect=True)
                cmds.setAttr(temp+'.rotateOrder', info['order'])
                before = [actual_values(info, t) for t in info['times'][0]]
                for attr, curve, offset in zip(ATTRS, info['curves'], info['offsets']):
                    copy = cmds.duplicate(curve, name='__rigEulerCurve#')[0]
                    copies.append(copy)
                    cmds.connectAttr(copy+'.output', temp+'.'+attr)
                    cmds.keyframe(copy, e=True, relative=True, valueChange=offset)
                cmds.filterCurve(*copies, filter='euler')
                values = [cmds.keyframe(k, q=True, vc=True) for k in copies]
                error = max(rotation_error(old, info['order'], new, info['order'])
                            for old, new in zip(before, zip(*values)))
                if error > 1e-4:
                    raise RuntimeError('过滤姿态校验失败：' + info['node'])
                for curve, offset, axis_values in zip(info['curves'], info['offsets'], values):
                    for i, value in enumerate(axis_values):
                        cmds.keyframe(curve, e=True, index=(i, i), valueChange=value-offset)
                reports.append(dict(node=info['node'], keys=len(before), max_error_degrees=error))
            finally:
                for n in copies + ([temp] if temp else []):
                    if cmds.objExists(n):
                        cmds.delete(n)
        return reports
    return _transaction(infos, apply)


def switch_order(objects, order):
    """Convert at existing rotation key times only; keep existing tangent types."""
    if order not in ORDERS:
        raise ValueError('无效的旋转顺序。')
    if not objects:
        raise ValueError('请选择物体。')
    target = ORDERS.index(order)
    infos = [describe(n, editable=True) for n in dict.fromkeys(objects)]
    infos = [info for info in infos if info['order'] != target]
    for info in infos:
        for curve in info['curves']:
            if curve and (cmds.getAttr(curve+'.preInfinity') or cmds.getAttr(curve+'.postInfinity')):
                raise ValueError('转换前请将循环/线性无限动画烘焙为关键帧：' + curve)
        times = _key_times(info)
        values = [actual_values(info, t) for t in times]
        converted = []
        previous = None
        for value in values:
            current = euler(value, info['order'])
            current.reorderIt(target)
            if previous is not None:
                current = current.closestSolution(previous)
                current = current.closestCut(previous)
            previous = current
            converted.append([math.degrees(v)-o for v, o in zip(current, info['offsets'])])
        info.update(samples=times, before=values, converted=converted)
    if not infos:
        return []
    def apply():
        reports = []
        for info in infos:
            node = info['node']
            cmds.setAttr(node+'.rotateOrder', target)
            animated = any(info['times'])
            if animated:
                for t, values in zip(info['samples'], info['converted']):
                    for attr, value, old_times in zip(ATTRS, values, info['times']):
                        if t in old_times:
                            cmds.keyframe(node+'.'+attr, e=True, time=(t,t), valueChange=value)
                        else:
                            # Euler axes are coupled. Complete XYZ at existing
                            # rotation times only; never add in-between frames.
                            cmds.setKeyframe(node, at=attr, time=t, value=value,
                                             itt='auto', ott='auto')
                for attr in ATTRS:
                    if cmds.keyframe(node+'.'+attr, q=True, tc=True) != info['samples']:
                        raise RuntimeError('关键帧时间校验失败，已恢复：'+node)
            else:
                for attr, value in zip(ATTRS, info['converted'][0]):
                    cmds.setAttr(node+'.'+attr, value)
            error = max(rotation_error(before, info['order'], actual_values(info, t), target)
                        for t, before in zip(info['samples'], info['before']))
            if error > 1e-4:
                raise RuntimeError('转换姿态校验失败，已恢复：' + node)
            reports.append(dict(node=node, order=order, keys=len(info['samples']) if animated else 0,
                                max_error_degrees=error, mode='existing_keys'))
        return reports
    return _transaction(infos, apply)
