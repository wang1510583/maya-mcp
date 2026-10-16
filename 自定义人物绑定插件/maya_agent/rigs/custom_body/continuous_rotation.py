"""Continuous quaternion artwork-independent spine rotation candidates."""
import math
import json

VERSION = '1.0.0'
ATTRIBUTE = 'continuousBodyRotationData'


class PoseMismatchError(ValueError):
    """Candidate was rolled back because it differs from the original solve."""


def candidate(rig, preserve_current_branch=True):
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    created = []
    namespace = rig['namespace']
    controls = rig['controls']

    def node(kind, label):
        result = cmds.createNode(kind, name=namespace + ':continuous_' + label, skipSelect=True)
        created.append(result)
        return result

    def product(first, second, label):
        result = node('quatProd', label)
        for index, value in enumerate((first, second), 1):
            plug = result + '.input%dQuat' % index
            if isinstance(value, str):
                cmds.connectAttr(value, plug)
            else:
                cmds.setAttr(plug, *value, type='double4')
        return result + '.outputQuat'

    def conjugate(source, matrix, label):
        quaternion = om.MTransformationMatrix(om.MMatrix(matrix)).rotation(asQuaternion=True)
        return product(product(list(quaternion), source, label + 'Pre'), list(quaternion.inverse()), label + 'Post')

    try:
        endpoints = {}
        for role in ('hips', 'chest'):
            rotation = node('eulerToQuat', role)
            cmds.connectAttr(controls[role] + '.rotate', rotation + '.inputRotate')
            cmds.connectAttr(controls[role] + '.rotateOrder', rotation + '.inputRotateOrder')
            endpoints[role] = rotation + '.outputQuat'
        inherited = namespace + ':bodyFollow_hipsInChest'
        if cmds.objExists(inherited):
            transformed = conjugate(endpoints['hips'], cmds.getAttr(inherited + '.matrixIn[0]'), 'Inherited')
            blend = node('quatSlerp', 'Follow')
            cmds.setAttr(blend + '.input1Quat', 0, 0, 0, 1, type='double4')
            cmds.connectAttr(transformed, blend + '.input2Quat')
            cmds.connectAttr(namespace + ':bodyFollow_inheritedRotation.target[0].weight', blend + '.inputT')
            endpoints['chest'] = product(endpoints['chest'], blend + '.outputQuat', 'ChestFollow')
        outputs = []
        for role, control in controls.items():
            if role in ('hips', 'chest'):
                continue
            stem = control[:-5]
            constraint = stem + '_orientConstraint'
            inputs = []
            for index, endpoint in enumerate(('hips', 'chest')):
                source = endpoints[endpoint]
                delta = stem + '_' + endpoint + 'Delta'
                if cmds.objExists(delta):
                    source = conjugate(source, cmds.getAttr(delta + '.matrixIn[0]'), role + endpoint)
                if preserve_current_branch:
                    reference = om.MEulerRotation(*[math.radians(value) for value in cmds.getAttr(constraint + '.target[%d].targetRotate' % index)[0]]).asQuaternion()
                    current = cmds.getAttr(source)[0]
                    if sum(first * second for first, second in zip(reference, current)) < 0:
                        negate = node('quatNegate', role + endpoint + 'Branch')
                        cmds.connectAttr(source, negate + '.inputQuat')
                        source = negate + '.outputQuat'
                scale = node('multiplyDivide', role + endpoint + 'XYZ')
                scalar = node('multDoubleLinear', role + endpoint + 'W')
                for axis in 'XYZ':
                    cmds.connectAttr(source + axis, scale + '.input1' + axis)
                    cmds.connectAttr(control + '.' + endpoint + 'Weight', scale + '.input2' + axis)
                cmds.connectAttr(source + 'W', scalar + '.input1')
                cmds.connectAttr(control + '.' + endpoint + 'Weight', scalar + '.input2')
                inputs.append((scale, scalar))
            addition = node('quatAdd', role + 'Sum')
            for index, (scale, scalar) in enumerate(inputs, 1):
                for axis in 'XYZ':
                    cmds.connectAttr(scale + '.output' + axis, addition + '.input%dQuat%s' % (index, axis))
                cmds.connectAttr(scalar + '.output', addition + '.input%dQuatW' % index)
            normalize = node('quatNormalize', role + 'Normalize')
            cmds.connectAttr(addition + '.outputQuat', normalize + '.inputQuat')
            rotation = node('quatToEuler', role + 'Euler')
            cmds.connectAttr(normalize + '.outputQuat', rotation + '.inputQuat')
            cmds.connectAttr(constraint + '.constraintRotateOrder', rotation + '.inputRotateOrder')
            outputs.append(dict(role=role, original=constraint + '.constraintRotate', replacement=rotation + '.outputRotate'))
        return dict(created=created, outputs=outputs)
    except Exception:
        if created:
            cmds.delete(created)
        raise


def enable(rig, sample_frames=None):
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    owner = rig['controls']['hips']
    if cmds.objExists(owner + '.' + ATTRIBUTE):
        return json.loads(cmds.getAttr(owner + '.' + ATTRIBUTE))
    frame = cmds.currentTime(query=True)
    data = candidate(rig)
    replaced = []
    watched = list(rig['controls'].values()) + rig['joints']
    before = {node: cmds.xform(node, query=True, worldSpace=True, matrix=True) for node in watched}
    try:
        largest = 0.0
        for sample in sorted(set(sample_frames or []) | {frame}):
            cmds.currentTime(sample)
            for row in data['outputs']:
                quaternions = [om.MEulerRotation(*[math.radians(value) for value in cmds.getAttr(row[key])[0]]).asQuaternion()
                               for key in ('original', 'replacement')]
                error = math.degrees(2 * math.acos(min(1, abs((quaternions[0] * quaternions[1].inverse()).w))))
                largest = max(largest, error)
                if error > 0.0001:
                    raise PoseMismatchError('连续旋转升级会改变已有姿态，已取消：%s，帧 %s，误差 %.6f 度' % (row['role'], sample, error))
        cmds.currentTime(frame)
        for row in data['outputs']:
            for destination in cmds.listConnections(row['original'], source=False, destination=True, plugs=True) or []:
                if cmds.connectionInfo(destination, sourceFromDestination=True) != row['original']:
                    raise ValueError('不支持单轴旋转输出连接：' + destination)
                replaced.append((row['original'], destination, row['replacement']))
                cmds.connectAttr(row['replacement'], destination, force=True)
        pose_error = max(abs(first - second) for node, matrix in before.items()
                         for first, second in zip(matrix, cmds.xform(node, query=True, worldSpace=True, matrix=True)))
        if pose_error > 0.0001:
            raise PoseMismatchError('连续旋转升级未保留姿态：%s' % pose_error)
        data.update(version=VERSION, replaced=replaced, max_rotation_error=largest, max_pose_error=pose_error)
        cmds.addAttr(owner, longName=ATTRIBUTE, dataType='string')
        cmds.setAttr(owner + '.' + ATTRIBUTE, json.dumps(data), type='string')
        rig['continuous_rotation'] = data
        rig.setdefault('nodes', []).extend(data['created'])
        return data
    except Exception:
        for source, destination, replacement in reversed(replaced):
            cmds.connectAttr(source, destination, force=True)
        cmds.delete(data['created'])
        if cmds.objExists(owner + '.' + ATTRIBUTE):
            cmds.deleteAttr(owner + '.' + ATTRIBUTE)
        raise
    finally:
        cmds.currentTime(frame)


def disable(rig):
    import maya.cmds as cmds

    plug = rig['controls']['hips'] + '.' + ATTRIBUTE
    if not cmds.objExists(plug):
        return False
    data = json.loads(cmds.getAttr(plug))
    for source, destination, replacement in data['replaced']:
        if cmds.connectionInfo(destination, sourceFromDestination=True) != replacement:
            raise ValueError('旋转连接已被修改，未覆盖：' + destination)
    for source, destination, replacement in data['replaced']:
        cmds.connectAttr(source, destination, force=True)
    cmds.delete(data['created'])
    cmds.deleteAttr(plug)
    rig.pop('continuous_rotation', None)
    return True
