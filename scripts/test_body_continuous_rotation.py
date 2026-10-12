"""Disposable checks for preserved body behavior and continuous rotation."""
import math
import uuid
import maya.cmds as cmds
import maya.api.OpenMaya as om
from maya_agent.rigs.custom_body import continuous_rotation


def quaternion(plug):
    return om.MEulerRotation(*[math.radians(value) for value in cmds.getAttr(plug)[0]]).asQuaternion()


def angle(first, second):
    return math.degrees(2 * math.acos(min(1, abs((first * second.inverse()).w))))


def verify_scene_boundary(rig, endpoint_role='hips', axis=1, start=-6):
    data = continuous_rotation.candidate(rig)
    created = data['created']
    endpoint = next(node for node in created if cmds.nodeType(node) == 'eulerToQuat' and node.split(':')[-1].startswith('continuous_' + endpoint_role))
    rotate = cmds.getAttr(endpoint + '.inputRotate')[0]
    base = om.MEulerRotation(*[math.radians(value) for value in rotate])
    cmds.disconnectAttr(cmds.connectionInfo(endpoint + '.inputRotate', sourceFromDestination=True), endpoint + '.inputRotate')
    row = next(row for row in data['outputs'] if row['role'] == 'spine02')
    source = row['original'].split('.')[0]
    old = cmds.createNode('orientConstraint', name='_continuousCheck_' + uuid.uuid4().hex[:8], skipSelect=True)
    created.append(old)
    cmds.setAttr(old + '.interpType', 1)
    for index in (0, 1):
        cmds.setAttr(old + '.target[%d].targetWeight' % index, cmds.getAttr(source + '.target[%d].targetWeight' % index))
        cmds.setAttr(old + '.target[%d].targetRotate' % index, *cmds.getAttr(source + '.target[%d].targetRotate' % index)[0])
    delta = source.replace('_orientConstraint', '_' + endpoint_role + 'Delta')
    prefix = om.MMatrix(cmds.getAttr(delta + '.matrixIn[0]'))
    suffix = om.MMatrix(cmds.getAttr(delta + '.matrixIn[2]'))
    previous = None
    largest_old = largest_new = 0
    try:
        for step in range(201):
            offset = start + step * .01
            angles = [0, 0, 0]
            angles[axis] = math.radians(offset)
            matrix = om.MEulerRotation(*angles).asMatrix() * base.asMatrix()
            euler = om.MTransformationMatrix(matrix).rotation().closestSolution(base)
            cmds.setAttr(endpoint + '.inputRotate', *[math.degrees(value) for value in euler])
            transformed = om.MTransformationMatrix(prefix * matrix * suffix).rotation()
            cmds.setAttr(old + '.target[%d].targetRotate' % (0 if endpoint_role == 'hips' else 1), *[math.degrees(value) for value in transformed])
            current = (quaternion(old + '.constraintRotate'), quaternion(row['replacement']))
            if previous:
                largest_old = max(largest_old, angle(previous[0], current[0]))
                largest_new = max(largest_new, angle(previous[1], current[1]))
            previous = current
        assert largest_old > 100, largest_old
        assert largest_new < 1, largest_new
        return dict(endpoint=endpoint_role, axis='XYZ'[axis], step=.01, old_jump=largest_old, new_step=largest_new)
    finally:
        cmds.delete(created)


def verify_existing_regressions():
    from scripts import test_body_direction as fixture
    from scripts import test_body_follow

    original = fixture.setup

    def setup(*args, **kwargs):
        rig = original(*args, **kwargs)
        continuous_rotation.enable(rig, sample_frames=[1, 2, 3, 4, 5])
        return rig

    fixture.setup = setup
    reports = []
    try:
        for count in (2, 4, 8):
            reports.append(fixture.verify(count=count))
            reports.append(test_body_follow.verify(count=count, animated=True, general=True))
        return reports
    finally:
        fixture.setup = original
