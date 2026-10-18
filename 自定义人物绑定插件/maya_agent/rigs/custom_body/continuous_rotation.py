"""Continuous quaternion artwork-independent spine rotation candidates."""
import math
import json

VERSION = '2.0.0'
ATTRIBUTE = 'continuousBodyRotationData'


def _registration(plug, value):
    import maya.cmds as cmds
    locked=cmds.getAttr(plug,lock=True)
    if locked:cmds.setAttr(plug,lock=False)
    try:cmds.setAttr(plug,value,type='string')
    finally:
        if locked:cmds.setAttr(plug,lock=True)


class PoseMismatchError(ValueError):
    """Candidate was rolled back because it differs from the original solve."""


def candidate(rig, preserve_current_branch=True, preserve_animation=True):
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    created = []
    selection = cmds.ls(selection=True,long=True) or []
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

    def local_rotation(control,label):
        rotation=node('eulerToQuat',label)
        cmds.connectAttr(control+'.rotate',rotation+'.inputRotate')
        cmds.connectAttr(control+'.rotateOrder',rotation+'.inputRotateOrder')
        axis=node('eulerToQuat',label+'RotateAxis')
        cmds.connectAttr(control+'.rotateAxis',axis+'.inputRotate')
        return product(axis+'.outputQuat',rotation+'.outputQuat',label+'Local')

    try:
        endpoints = {}
        for role in ('hips', 'chest'):
            control=controls[role]
            source=local_rotation(control,role)
            index=0 if role=='hips' else len(controls)-1
            effective=namespace+':bodyMatch_effective'+str(index)
            if cmds.objExists(effective):
                # Keep the authored Euler lift through each factor. Decomposing
                # their matrix product first would recreate the +/-180 branch.
                space=cmds.connectionInfo(effective+'.matrixIn[2]',sourceFromDestination=True)
                if not space.endswith('.matrix'):raise ValueError('不支持的身体匹配旋转空间：'+space)
                offset=node('decomposeMatrix',role+'Offset')
                cmds.connectAttr(control+'.offsetParentMatrix',offset+'.inputMatrix')
                inverse=node('quatInvert',role+'OffsetInverse')
                cmds.connectAttr(offset+'.outputQuat',inverse+'.inputQuat')
                source=product(source,offset+'.outputQuat',role+'WithOffset')
                source=product(source,local_rotation(space.split('.')[0],role+'Match'),role+'WithMatch')
                source=product(source,inverse+'.outputQuat',role+'Matched')
            endpoints[role] = source
        inherited = namespace + ':bodyFollow_hipsInChest'
        if cmds.objExists(inherited):
            transformed = conjugate(endpoints['hips'], cmds.getAttr(inherited + '.matrixIn[0]'), 'Inherited')
            axis_angle = node('quatToAxisAngle', 'FollowAxis')
            cmds.connectAttr(transformed, axis_angle + '.inputQuat')
            weight = node('multDoubleLinear', 'FollowWeight')
            cmds.connectAttr(axis_angle + '.outputAngle', weight + '.input1')
            cmds.connectAttr(namespace + ':bodyFollow_inheritedRotation.target[0].weight', weight + '.input2')
            blend = node('axisAngleToQuat', 'Follow')
            cmds.connectAttr(axis_angle + '.outputAxis', blend + '.inputAxis')
            cmds.connectAttr(weight + '.output', blend + '.inputAngle')
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
            outputs.append(dict(role=role, original=constraint + '.constraintRotate', replacement=rotation + '.outputRotate', continuous_quat=normalize + '.outputQuat'))
        reference_data = None
        if preserve_animation:
            from .rotation_reference import Reference
            reference = Reference(namespace, created)
            for row in outputs:
                original_ref = reference.source(row['original'])
                continuous_ref = reference.source(row['continuous_quat'])
                source = row['original'].split('.')[0]
                original_quat = node('eulerToQuat', row['role']+'ReferenceEuler')
                cmds.connectAttr(original_ref,original_quat+'.inputRotate')
                cmds.connectAttr(original_ref.split('.')[0]+'.constraintRotateOrder',original_quat+'.inputRotateOrder')
                inverse = node('quatInvert',row['role']+'ReferenceInverse')
                cmds.connectAttr(continuous_ref,inverse+'.inputQuat')
                correction = product(original_quat+'.outputQuat',inverse+'.outputQuat',row['role']+'ReferenceCorrection')
                corrected = product(correction,row['continuous_quat'],row['role']+'PreservedMotion')
                rotation = node('quatToEuler',row['role']+'PreservedEuler')
                cmds.connectAttr(corrected,rotation+'.inputQuat')
                cmds.connectAttr(source+'.constraintRotateOrder',rotation+'.inputRotateOrder')
                row['replacement']=rotation+'.outputRotate'
            reference_data=dict(version='1.0.0',group=reference.group,copies=reference.copies)
        return dict(created=created, outputs=outputs, animation_reference=reference_data)
    except Exception:
        if created:
            cmds.delete(created)
        raise
    finally:
        cmds.select(selection,replace=True) if selection else cmds.select(clear=True)


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


def repair_character(root, sample_frames=None):
    """Explicit existing-character repair. Preserve authored curves and native interpolation."""
    import maya.cmds as cmds
    plug=root+'.integratedRigData'
    if cmds.referenceQuery(root,isNodeReferenced=True):raise ValueError('引用角色需在原绑定文件中显式修复')
    original=cmds.getAttr(plug);metadata=json.loads(original)
    part=metadata.get('parts',{}).get('body')
    if not part:raise ValueError('当前角色没有身体绑定')
    owner=part['controls']['hips']+'.'+ATTRIBUTE
    if cmds.objExists(owner):
        existing=json.loads(cmds.getAttr(owner))
        if existing.get('version')==VERSION:return dict(version=VERSION,already_enabled=True)
        raise ValueError('当前角色已有其他版本的连续旋转，请先显式恢复旧求解后升级')
    restore=dict(body=json.loads(json.dumps(part)),fallback=metadata.get('continuous_rotation_fallback'),repair=metadata.get('continuous_rotation_repair'))
    if sample_frames is None:
        start=cmds.playbackOptions(query=True,minTime=True);end=cmds.playbackOptions(query=True,maxTime=True)
        if end-start>10000:raise ValueError('动画范围过长，请显式指定核对帧')
        sample_frames=[start+i*.25 for i in range(int((end-start)*4)+1)]
    sample_frames=list(sample_frames)
    enabled=False
    try:
        data=enable(part,sample_frames=sample_frames);enabled=True
        data['character_restore']=restore;data['checked_frames']=sorted(set(sample_frames))
        cmds.setAttr(owner,json.dumps(data),type='string')
        metadata.pop('continuous_rotation_fallback',None)
        metadata['continuous_rotation_repair']=dict(version=VERSION,reference='independent_native_animation',checked_frames=len(data['checked_frames']))
        _registration(plug,json.dumps(metadata))
        return dict(version=VERSION,created=len(data['created']),checked_frames=len(data['checked_frames']),max_rotation_error=data['max_rotation_error'],max_pose_error=data['max_pose_error'])
    except Exception:
        if enabled:disable(part)
        _registration(plug,original)
        raise


def restore_character(root):
    """Restore the previous solve/registration; never replace other character parts."""
    import maya.cmds as cmds
    plug=root+'.integratedRigData';metadata=json.loads(cmds.getAttr(plug));part=metadata['parts']['body']
    owner=part['controls']['hips']+'.'+ATTRIBUTE
    if not cmds.objExists(owner):return False
    data=json.loads(cmds.getAttr(owner));restore=data.get('character_restore')
    if not restore:raise ValueError('该连续旋转系统没有角色升级恢复记录')
    disable(part);metadata['parts']['body']=restore['body']
    for key,name in (('continuous_rotation_fallback','fallback'),('continuous_rotation_repair','repair')):
        if restore.get(name) is None:metadata.pop(key,None)
        else:metadata[key]=restore[name]
    _registration(plug,json.dumps(metadata))
    return True
