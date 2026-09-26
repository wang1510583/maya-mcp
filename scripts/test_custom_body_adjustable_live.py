"""Run with runpy inside Maya; only temporary owned rigs are changed."""
import math
import uuid
import maya.cmds as cmds
from maya_agent.tools.registry import run_tool


def run_case(count, height):
    before = set(cmds.ls(long=True) or [])
    selection = cmds.ls(selection=True, long=True) or []
    namespace = cmds.namespaceInfo(currentNamespace=True)
    frame = cmds.currentTime(query=True)
    dirty = cmds.file(query=True, modified=True)
    poses = {n: cmds.xform(n, query=True, worldSpace=True, matrix=True)
             for n in cmds.ls(type='transform', long=True) + cmds.ls(type='joint', long=True)}
    ns = '_CBR_PARAM_' + uuid.uuid4().hex[:8]
    rigs = []
    checks = []

    def near(actual, expected):
        assert all(abs(a-b) < 2e-5 for a, b in zip(actual, expected)), (actual, expected)

    def position(node):
        return cmds.xform(node, query=True, worldSpace=True, translation=True)

    try:
        response = run_tool('create_custom_body_rig', {'namespace': ns, 'segment_count': count, 'height': height})
        assert response.ok, response.error
        rig = response.data
        rigs.append(rig)
        assert not cmds.ls(ns + ':*', type='displayLayer')
        for role, ctrl in rig['controls'].items():
            assert cmds.getAttr(ctrl + '.overrideEnabled')
            assert cmds.getAttr(ctrl + '.overrideColor') == (14 if role in ('hips', 'chest') else 17)
        assert cmds.getAttr(rig['joints'][0] + '.overrideColor') == 18
        checks.append('no redundant layers and original display colors retained')
        assert len(rig['joints']) == len(rig['controls']) == count
        assert cmds.getAttr(ns + ':hips_zero.customBodySegmentCount') == count
        assert cmds.getAttr(ns + ':hips_zero.customBodyHeight') == height
        step = height / (count - 1)
        controls = list(rig['controls'].values())
        for i, (joint, ctrl) in enumerate(zip(rig['joints'], controls)):
            near(position(joint), [0, i * step, 0])
            near(position(ctrl), position(joint))
            shape = cmds.listRelatives(ctrl, shapes=True, fullPath=True)[0]
            assert cmds.getAttr(shape + '.spans') == 15
        checks.append('count, height, baseline positions and control curves')

        chest, hips = rig['controls']['chest'], rig['controls']['hips']
        factors = [i/(count-1) for i in range(count)] if count != 4 else [0, .333, .667, 1]
        cmds.setAttr(chest + '.translate', 3, 1.5, -1.2, type='double3')
        for i, (joint, fraction) in enumerate(zip(rig['joints'], factors)):
            near(position(joint), [3*fraction, i*step+1.5*fraction, -1.2*fraction])
        cmds.setAttr(chest + '.translate', 0, 0, 0, type='double3')
        cmds.setAttr(hips + '.translate', 1.2, -.5, 2, type='double3')
        for i, joint in enumerate(rig['joints']):
            near(position(joint), [1.2, i*step-.5, 2])
        cmds.setAttr(hips + '.translate', 0, 0, 0, type='double3')
        checks.append('chest translation distribution and hips translation')

        for endpoint in (chest, hips):
            cmds.setAttr(endpoint + '.rotateZ', 30)
            for i, ctrl in enumerate(controls[1:-1], 1):
                moving = i if endpoint == chest else count-1-i
                stationary = count-1-moving
                half = math.radians(15)
                angle = math.degrees(2*math.atan2(moving*math.sin(half), moving*math.cos(half)+stationary))
                connect = ctrl.removesuffix('_ctrl') + '_connect'
                near([cmds.getAttr(connect + '.rotateZ')], [angle])
            assert all(math.isfinite(x) for joint in rig['joints'] for x in position(joint))
            cmds.setAttr(endpoint + '.rotateZ', 0)
        checks.append('weighted quaternion rotation from both endpoints')

        if count > 2:
            middle = count // 2
            ctrl = controls[middle]
            cmds.setAttr(ctrl + '.translateX', .75)
            for i, joint in enumerate(rig['joints']):
                near(position(joint), [.75 if i >= middle else 0, i*step, 0])
            cmds.setAttr(ctrl + '.translateX', 0)
            cmds.setAttr(ctrl + '.rotateZ', 20)
            dx, dy = -step*math.sin(math.radians(20)), step*(math.cos(math.radians(20))-1)
            for i, joint in enumerate(rig['joints']):
                near(position(joint), [dx if i > middle else 0, i*step+(dy if i > middle else 0), 0])
            cmds.setAttr(ctrl + '.rotateZ', 0)
            checks.append('independent middle control translation and downstream bending')

        if count == 6:
            second = run_tool('create_custom_body_rig', {'namespace': ns, 'segment_count': 3, 'height': 4})
            assert second.ok, second.error
            rigs.append(second.data)
            assert second.data['namespace'] == ns + '_02'
            assert {e['source'] for e in rig['display_layer_connections']}.isdisjoint(
                {e['source'] for e in second.data['display_layer_connections']})
            cmds.setAttr(hips + '.translateX', 4)
            near(position(second.data['joints'][0]), [0, 0, 0])
            checks.append('different counts coexist independently')

        current = set(cmds.ls(long=True) or [])
        for args in ({'segment_count': 1}, {'segment_count': 65}, {'segment_count': True},
                     {'height': 0}, {'height': float('nan')}):
            invalid = run_tool('create_custom_body_rig', dict(namespace=ns+'_invalid', **args))
            assert not invalid.ok
            assert set(cmds.ls(long=True) or []) == current
        checks.append('invalid dimensions rejected before scene edits')
    finally:
        for rig in reversed(rigs):
            for node in reversed(rig['nodes']):
                if cmds.objExists(node):
                    cmds.delete(node)
            if cmds.namespace(exists=rig['namespace']):
                cmds.namespace(removeNamespace=rig['namespace'])
        cmds.namespace(setNamespace=namespace)
        cmds.select(selection, replace=True) if selection else cmds.select(clear=True)
        assert set(cmds.ls(long=True) or []) == before
        assert cmds.currentTime(query=True) == frame
        for node, matrix in poses.items():
            near(cmds.xform(node, query=True, worldSpace=True, matrix=True), matrix)
        cmds.file(modified=dirty)
    return {'segment_count': count, 'height': height, 'checks': checks, 'original_scene_preserved': True}
