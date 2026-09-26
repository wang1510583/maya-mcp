"""Fit the captured arm solver to three ordered scene targets."""
import json
import math


def ordered_selection():
    import maya.cmds as c
    if not c.selectPref(q=True, trackSelectionOrder=True):
        raise ValueError('请先打开手臂系统窗口，再按肩、肘、腕的顺序重新逐个选择。')
    return c.ls(orderedSelection=True, long=True) or []


def inspect(targets, allow_animation=False):
    import maya.cmds as c
    from maya_agent.rigs.custom_body.targets import inspect as inspect_targets
    if not isinstance(targets, (list, tuple)) or len(targets) != 3:
        raise ValueError('请按肩 → 肘 → 腕的顺序，恰好选择 3 根骨骼或物体。')
    samples, _ = inspect_targets(targets, allow_animation=allow_animation)
    for sample in samples:
        sample['position'] = c.xform(sample['node'], q=True, ws=True, rotatePivot=True)
        node = sample['node']
        while node:
            for attr in ('scale', 'shear', 'rotateAxis', 'rotatePivot', 'rotatePivotTranslate',
                         'scalePivot', 'scalePivotTranslate', 'jointOrient', 'rotateOrder'):
                if allow_animation and attr == 'scale': continue
                plugs = [node+'.'+attr] + [node+'.'+attr+a for a in 'XYZ']
                for plug in plugs:
                    if c.objExists(plug) and c.listConnections(plug, s=True, d=False):
                        raise ValueError('目标或父级有动画/驱动属性，未覆盖：'+plug)
            parents = c.listRelatives(node, parent=True, fullPath=True) or []
            node = parents[0] if parents else None
    lengths = [math.dist(a['position'], b['position']) for a, b in zip(samples, samples[1:])]
    if min(lengths) < 1e-5 or math.dist(samples[0]['position'], samples[2]['position']) < 1e-5:
        raise ValueError('肩、肘、腕的位置不能重合；完全折叠的手臂无法确定求解方向。')
    return samples, lengths


def _geometry(samples):
    import maya.api.OpenMaya as om
    a, b, end = [om.MVector(s['position']) for s in samples]
    axis = (end-a).normal()
    bend = b - (a + axis*((b-a)*axis))
    straight = bend.length() < max((b-a).length(), (end-b).length()) * 1e-6
    if straight:
        # Prefer the shoulder's local Y; choose a deterministic world axis if parallel.
        m = samples[0]['matrix']
        hint = om.MVector(m[4:7])
        bend = hint-axis*(hint*axis)
        if bend.length() < 1e-6:
            hint = min((om.MVector(1,0,0), om.MVector(0,1,0), om.MVector(0,0,1)),
                       key=lambda v: abs(v*axis))
            bend = hint-axis*(hint*axis)
    bend.normalize()
    normal = (axis ^ bend).normal()
    pole = b + bend * ((b-a).length()+(end-b).length())

    def frame(position, direction):
        x = direction.normal()
        y = (normal ^ x).normal()
        return [x.x,x.y,x.z,0, y.x,y.y,y.z,0, normal.x,normal.y,normal.z,0,
                position.x,position.y,position.z,1]
    return [frame(a,b-a), frame(b,end-b), frame(end,end-b)], list(pole), straight


def fit(rig, samples, lengths):
    import maya.cmds as c
    ns = rig['namespace']+':'
    frames, pole, straight = _geometry(samples)
    # Set lengths before requesting evaluation at the new input pose.
    for i, length in enumerate(lengths, 1):
        c.setAttr(ns+'strech_ik_foot1.lenght_joint_'+str(i), length)
    c.xform(ns+'joint1', ws=True, translation=samples[0]['position'])
    for node, matrix in zip(('shldrFK_L1','armFK_L1','handFK_L1'), frames):
        c.xform(ns+node, ws=True, matrix=matrix)
    c.setAttr(ns+'hand_L1.translate', 0, 0, 0)
    c.setAttr(ns+'hand_L1.rotate', 0, 0, 0)
    c.xform(ns+'elb_L1', ws=True, translation=pole)
    follow = c.pointConstraint(ns+'shldrFK_L1', ns+'joint1', maintainOffset=False,
                               name=ns+'shoulder_follow_pointConstraint')[0]
    rig['nodes'].append(follow)
    # Keep the pole reference on the existing elbow-roll system, recalibrated at this pose.
    c.xform(ns+'locator3', ws=True, translation=pole)
    for sample, joint in zip(samples, rig['joints']):
        error = math.dist(c.xform(joint, q=True, ws=True, translation=True), sample['position'])
        if error > max(sum(lengths)*1e-6, 1e-5):
            raise RuntimeError('手臂匹配失败：{}，位置误差 {}'.format(joint, error))
    # Appearance follows the new arm size, without scaling the solver hierarchy.
    size = sum(lengths)/15.275443977366117
    for joint in c.ls(ns+'*', type='joint') or []:
        if not c.listConnections(joint+'.radius', s=True, d=False):
            c.setAttr(joint+'.radius', c.getAttr(joint+'.radius')*size)
    for shape in c.ls(ns+'*', type='locator') or []:
        for axis in 'XYZ':
            c.setAttr(shape+'.localScale'+axis, c.getAttr(shape+'.localScale'+axis)*size)
    c.addAttr(rig['root'], longName='armTargets', dataType='string')
    c.setAttr(rig['root']+'.armTargets', json.dumps([s['node'] for s in samples]), type='string', lock=True)
    rig.update(mode='selection', lengths=lengths, straight_input=straight,
               warnings=['三点共线，已根据肩部朝向设置默认弯曲方向，可移动肘部定位器调整。'] if straight else [])


def connect(rig, samples, drivers=None):
    import maya.cmds as c
    mappings = []
    for i, (joint, sample) in enumerate(zip(rig['joints'], samples), 1):
        driver = drivers[i-1] if drivers else joint
        constraint = c.parentConstraint(driver, sample['node'], maintainOffset=not bool(drivers),
                    name=rig['namespace']+':target{:02d}_parentConstraint'.format(i))[0]
        rig['nodes'].append(constraint)
        mappings.append({'target':sample['node'], 'joint':joint, 'constraint':constraint, 'driver':driver})
    for sample in samples:
        matrix = c.xform(sample['node'], q=True, ws=True, matrix=True)
        if max(abs(a-b) for a,b in zip(matrix,sample['world_matrix'])) > 1e-5:
            raise RuntimeError('约束使目标姿态变化，已取消：'+sample['node'])
    return mappings


def build_from_selection(targets=None, namespace='customArm', drive_targets=True, copy_animation=False,
                         start_frame=None, end_frame=None, sample_step=1.0, side='L'):
    import maya.cmds as c
    from . import build
    from maya_agent.rigs.custom_body.targets import restore
    from maya_agent.rigs.custom_body.animation import frame_range
    from . import sides
    sides.validate(side)
    if not isinstance(drive_targets, bool):
        raise ValueError('drive_targets 必须是布尔值')
    if not isinstance(copy_animation,bool):raise ValueError('copy_animation 必须是布尔值')
    if copy_animation and not drive_targets:raise ValueError('拷贝动画需要勾选“驱动所选骨骼 / 物体”。')
    frames=frame_range(c.playbackOptions(q=True,minTime=True) if start_frame is None else start_frame,
                       c.playbackOptions(q=True,maxTime=True) if end_frame is None else end_frame,
                       sample_step) if copy_animation else []
    samples, lengths = inspect(ordered_selection() if targets is None else targets, allow_animation=copy_animation)
    old_selection = c.ls(sl=True, long=True) or []
    auto = c.autoKeyframe(q=True, state=True)
    undo = c.undoInfo(q=True, state=True)
    rig = None
    transfer = None
    if undo: c.undoInfo(openChunk=True, chunkName='CreateCustomArmRig')
    try:
        c.autoKeyframe(state=False)
        rig = build(namespace=namespace)
        fit(rig, samples, lengths)
        if copy_animation:
            from .animation import Transfer
            transfer=Transfer(rig,samples,frames)
            transfer.capture()
            transfer.detach()
            drivers=transfer.prepare_drivers()
            rig['target_mapping']=connect(rig,samples,drivers=drivers)
        else:
            rig['target_mapping'] = connect(rig, samples) if drive_targets else []
        rig['animation_transfer']=transfer.bake(rig['target_mapping']) if transfer else None
        rig['drive_targets'] = drive_targets
        sides.apply(rig, side)
        return rig
    except Exception:
        if transfer:transfer.release_backup()
        if rig:
            # Includes constraints parented below external targets. Never delete targets.
            # Maya can cascade deletion from a driver into a constrained empty transform.
            # Remove owned constraints first, while both ends of the connection exist.
            for n in c.ls(rig['namespace']+':*', type='constraint', long=True) or []:
                if c.objExists(n): c.delete(n)
            for n in sorted(c.ls(rig['namespace']+':*', long=True) or [],
                            key=lambda n:n.count('|'), reverse=True):
                if c.objExists(n): c.delete(n)
            if c.namespace(exists=rig['namespace']): c.namespace(removeNamespace=rig['namespace'])
        if transfer:transfer.rollback()
        elif not copy_animation:restore(samples)
        raise
    finally:
        try:
            if transfer:c.currentTime(transfer.time)
            c.autoKeyframe(state=auto)
            existing=[n for n in old_selection if c.objExists(n)]
            c.select(existing, r=True) if existing else c.select(clear=True)
        finally:
            if undo: c.undoInfo(closeChunk=True)
