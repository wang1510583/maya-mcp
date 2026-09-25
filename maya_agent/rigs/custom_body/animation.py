"""World-space animation handoff through temporary baked locators.

Source curves are disconnected, not destroyed. A network node retains their message
links and exact connection map, including keys outside the requested bake interval.
All curve/node edits participate in the caller's single undo chunk.
"""
import json
import math

from .targets import CHANNELS


def frame_range(start, end, step=1.0):
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in (start, end, step)) or step <= 0 or end < start:
        raise ValueError('动画起止帧必须为有限数字，结束帧不能小于开始帧，采样间隔必须大于零。')
    if (end-start)/step > 10000:
        raise ValueError('一次最多烘焙 10001 个采样帧，请缩短帧范围或增大采样间隔。')
    frames = [float(start+i*step) for i in range(int(math.floor((end-start)/step))+1)]
    if end-frames[-1] > 1e-8:
        frames.append(float(end))
    if len(frames) > 10001:
        raise ValueError('一次最多烘焙 10001 个采样帧。')
    return frames


def _rigid(matrix):
    import maya.api.OpenMaya as om
    transform = om.MTransformationMatrix(om.MMatrix(matrix))
    rigid = transform.rotation(asQuaternion=True).asMatrix()
    values = list(rigid)
    values[12:15] = matrix[12:15]
    return om.MMatrix(values)


def _key_channels(c, node, frame, values):
    for attr, value in zip(CHANNELS, values):
        c.setKeyframe(node, attribute=attr, time=frame, value=value,
                      inTangentType='linear', outTangentType='linear')
    # setKeyframe(value=...) may leave an already evaluated output cached.
    c.dgdirty(node)


def _curves(ctx, node, temporary=False):
    c = ctx.cmds
    curves = []
    for attr in CHANNELS:
        curve = c.createNode('animCurveTL' if attr.startswith('translate') else 'animCurveTA',
                             name=node.split('|')[-1] + '_' + attr + '_bake', skipSelect=True)
        ctx.created.append(curve)
        c.connectAttr('time1.outTime', curve + '.input')
        c.connectAttr(curve + '.output', node + '.' + attr)
        curves.append(curve)
    return curves


class Transfer:
    def __init__(self, ctx, samples, frames):
        self.ctx, self.c, self.samples, self.frames = ctx, ctx.cmds, samples, frames
        self.time = self.c.currentTime(query=True)
        self.temporary = []
        self.locators = []
        self.motion = []
        self.edges = []
        self.detached = []
        self.backup = None
        for sample in samples:
            for attr in CHANNELS:
                dst = sample['node'] + '.' + attr
                src = self.c.connectionInfo(dst, sourceFromDestination=True)
                if src:
                    self.edges.append({'source': src, 'destination': dst})

    def capture(self):
        """Sample all inputs first, while the original hierarchy/animation is untouched."""
        import maya.api.OpenMaya as om
        c, ctx = self.c, self.ctx
        group = c.createNode('transform', name=ctx.namespace + ':animationCapture', skipSelect=True)
        ctx.created.append(group)
        self.temporary.append(group)
        c.setAttr(group + '.visibility', False)
        for index in range(len(self.samples)):
            locator = c.createNode('transform', name=ctx.namespace + ':capture{:02d}'.format(index+1),
                                   parent=group, skipSelect=True)
            ctx.created.append(locator)
            shape = c.createNode('locator', name=locator+'Shape', parent=locator, skipSelect=True)
            ctx.created.append(shape)
            self.temporary.extend([locator, shape])
            self.locators.append(locator)
            self.temporary.extend(_curves(ctx, locator, temporary=True))
        previous = [None] * len(self.samples)
        try:
            for frame in self.frames:
                c.currentTime(frame, edit=True)
                matrices = []
                for index, (sample, locator) in enumerate(zip(self.samples, self.locators)):
                    matrix = c.xform(sample['node'], query=True, worldSpace=True, matrix=True)
                    if not all(math.isfinite(v) for v in matrix):
                        raise ValueError('动画采样出现无效矩阵：' + sample['node'])
                    tm = om.MTransformationMatrix(om.MMatrix(matrix))
                    scale = tm.scale(om.MSpace.kWorld)
                    # Scale curves remain connected to the originals, including animated parents.
                    # Their values can change; parent-constraint fitting still requires rigid frames.
                    if (min(scale) <= 0 or max(scale)-min(scale) > 1e-5
                            or max(abs(v) for v in tm.shear(om.MSpace.kWorld)) > 1e-5):
                        raise ValueError('采样帧 {} 存在非均匀/非正缩放或剪切，未替换动画：{}'.format(frame, sample['node']))
                    euler = tm.rotation(asQuaternion=True).asEulerRotation()
                    if previous[index] is not None:
                        euler = euler.closestSolution(previous[index])
                    previous[index] = euler
                    _key_channels(c, locator, frame, matrix[12:15] + [math.degrees(v) for v in (euler.x,euler.y,euler.z)])
                    matrices.append(matrix)
                self.motion.append(matrices)
        finally:
            c.currentTime(self.time, edit=True)

    def detach(self):
        c, ctx = self.c, self.ctx
        self.backup = c.createNode('network', name=ctx.namespace + ':sourceAnimationBackup', skipSelect=True)
        ctx.created.append(self.backup)
        c.addAttr(self.backup, longName='originalConnections', dataType='string')
        c.setAttr(self.backup+'.originalConnections', json.dumps(self.edges), type='string', lock=True)
        c.addAttr(self.backup, longName='sourceCurves', attributeType='message', multi=True)
        sources = list(dict.fromkeys(edge['source'].split('.')[0] for edge in self.edges))
        for i, node in enumerate(sources):
            c.connectAttr(node + '.message', self.backup + '.sourceCurves[{}]'.format(i))
        for edge in self.edges:
            c.disconnectAttr(edge['source'], edge['destination'])
            self.detached.append(edge)
        # Disconnecting curves must leave the rig construction pose unchanged.
        from .targets import restore
        restore(self.samples)

    def rollback(self):
        """Called after new output constraints are removed; original curves remain intact."""
        c = self.c
        for sample in self.samples:
            for attr, value in sample['channels'].items():
                plug = sample['node']+'.'+attr
                if not c.connectionInfo(plug, isDestination=True):
                    c.setAttr(plug, value)
        for edge in self.detached:
            if not c.isConnected(edge['source'], edge['destination']):
                c.connectAttr(edge['source'], edge['destination'], force=False)
        c.currentTime(self.time, edit=True)

    def release_backup(self):
        # Maya deletes upstream animCurves when deleting a network with message inputs.
        # Disconnect these first so rollback never destroys the caller's source curves.
        if self.backup and self.c.objExists(self.backup):
            sources = list(dict.fromkeys(edge['source'].split('.')[0] for edge in self.edges))
            for i, node in enumerate(sources):
                src, dst = node+'.message', self.backup+'.sourceCurves[{}]'.format(i)
                if self.c.isConnected(src, dst):
                    self.c.disconnectAttr(src, dst)

    def verify(self, mappings):
        maximum = 0.0
        for frame, matrices in reversed(list(zip(self.frames, self.motion))):
            self.c.currentTime(frame, edit=True)
            for mapping, expected in zip(mappings, matrices):
                actual = self.c.xform(mapping['target'], query=True, worldSpace=True, matrix=True)
                error = max(abs(a-b) for a,b in zip(actual, expected))
                maximum = max(maximum, error)
                if error > 1e-4:
                    raise RuntimeError('动画最终核对失败：{}，帧 {}；已取消转换。'.format(mapping['target'], frame))
        return maximum

    def bake(self, mappings):
        import maya.api.OpenMaya as om
        c, ctx = self.c, self.ctx
        controls = [row['control'] for row in mappings]
        for control in controls:
            _curves(ctx, control)
        # A zero initial key restores the captured rest pose before evaluating the chain.
        for control in controls:
            _key_channels(c, control, self.time, [0]*6)
        previous = {}
        last = len(controls)-1
        rest_previous = om.MMatrix(self.samples[-2]['matrix'])
        rest_chest = om.MMatrix(self.samples[-1]['matrix'])
        offset = om.MVector(*[b-a for a,b in zip(self.samples[-2]['position'],self.samples[-1]['position'])]) * rest_previous.inverse()
        weight = c.getAttr(controls[-2]+'.chestWeight') / (c.getAttr(controls[-2]+'.chestWeight')+c.getAttr(controls[-2]+'.hipsWeight')) if last > 1 else 0.0

        def local_values(control, desired):
            parent = c.listRelatives(control, parent=True, fullPath=True)[0]
            local = desired * om.MMatrix(c.xform(parent, query=True, worldSpace=True, matrix=True)).inverse()
            tm = om.MTransformationMatrix(local)
            rotation = tm.rotation(asQuaternion=True).asEulerRotation()
            if control in previous:
                rotation = rotation.closestSolution(previous[control])
            previous[control] = rotation
            position = tm.translation(om.MSpace.kTransform)
            return [position.x,position.y,position.z] + [math.degrees(v) for v in (rotation.x,rotation.y,rotation.z)]

        max_error = 0.0
        for frame, matrices in zip(self.frames, self.motion):
            c.currentTime(frame, edit=True)
            desired = [_rigid(c.xform(locator, query=True, worldSpace=True, matrix=True)) for locator in self.locators]
            # Set endpoint rotations before solving the intermediate rest-frame blends.
            _key_channels(c, controls[0], frame, local_values(controls[0], desired[0]))
            chest_values = local_values(controls[-1], desired[-1])
            previous_rotation = om.MTransformationMatrix(desired[-2]).rotation(asQuaternion=True).asMatrix()
            last_segment = offset * previous_rotation
            desired_points = [om.MVector(*list(matrix)[12:15]) for matrix in desired]
            chest_delta = (desired_points[-1]-desired_points[-2]-last_segment) / (1.0-weight)
            chest_local = chest_delta * rest_chest.inverse()
            chest_values[:3] = [chest_local.x,chest_local.y,chest_local.z]
            _key_channels(c, controls[-1], frame, chest_values)
            for control, matrix in zip(controls[1:-1], desired[1:-1]):
                _key_channels(c, control, frame, local_values(control, matrix))
            # Verify target matrices, not merely controller values or key counts.
            for mapping, expected in zip(mappings, matrices):
                actual = c.xform(mapping['target'], query=True, worldSpace=True, matrix=True)
                error = max(abs(a-b) for a,b in zip(actual,expected))
                max_error = max(max_error,error)
                if error > 1e-4:
                    raise RuntimeError('动画核对失败：{}，帧 {}，误差 {:.6g}；已取消转换。'.format(mapping['target'],frame,error))
        # Remove the construction key when it is outside the requested sample grid.
        if all(abs(frame-self.time)>1e-8 for frame in self.frames):
            for control in controls:
                c.cutKey(control, attribute=list(CHANNELS), time=(self.time,self.time), clear=True)
        for node in reversed(self.temporary):
            if c.objExists(node):
                c.delete(node)
        ctx.created[:] = [node for node in ctx.created if node not in self.temporary]
        max_error = max(max_error, self.verify(mappings))
        return {'start_frame':self.frames[0], 'end_frame':self.frames[-1], 'sample_count':len(self.frames),
                'max_world_matrix_error':max_error,'source_animation_backup':self.backup,
                'original_curve_count':len(set(edge['source'].split('.')[0] for edge in self.edges)),
                'scale_animation':'preserved_on_targets',
                'temporary_locators_removed':True}
