"""Run the installed Easy Rig MEL on a disposable replica, preserving the scene."""
import importlib
import math
import runpy
from pathlib import Path
import maya.cmds as c
import maya.mel as mel
import maya_agent.rigs.soft_limb as limb


def verify():
    def rigid_matrix(matrix):
        # The MEL matches position/orientation, not the helper's length-driven scale.
        matrix = list(matrix)
        for start in (0, 4, 8):
            length = math.sqrt(sum(v*v for v in matrix[start:start+3]))
            matrix[start:start+3] = [v/length for v in matrix[start:start+3]]
        return matrix
    importlib.reload(limb)
    before_nodes = set(c.ls(long=True))
    before_matrices = {n: c.xform(n, q=True, ws=True, m=True)
                       for n in c.ls(type='transform', long=True)}
    before_keys = {n: (c.keyframe(n, q=True, tc=True), c.keyframe(n, q=True, vc=True))
                   for n in c.ls(type='animCurve')}
    selection = c.ls(sl=True, long=True) or []
    frame = c.currentTime(q=True)
    auto = c.autoKeyframe(q=True, state=True)
    old_namespace = c.namespaceInfo(currentNamespace=True)
    ns = None
    try:
        assert mel.eval('exists kurok_recalculate_system'), 'Load Easy Rig recalculation MEL first'
        time_range = mel.eval('EasyGameRig4_0_dfc2513778a513e560ec81c8f3df6563()')
        assert abs(time_range[1] - time_range[0] - 1) < 1e-6, 'Use a single current frame'
        c.autoKeyframe(state=False)
        rig = limb.build(namespace='_recalculateCheck', offset=(22, 0, 0))
        ns = rig['namespace']
        prefix = ns + ':'
        base_checks = runpy.run_path(str(Path(__file__).with_name('test_soft_limb_live.py')))['verify'](ns)
        c.setAttr(prefix + 'hand_L1.translateY', c.getAttr(prefix + 'hand_L1.translateY') - 2)
        pairs = [('base_L1', 'shldrFK_L1'), ('base_L2', 'armFK_L1'),
                 ('base_L3', 'handFK_L1'), ('locator3', 'elb_L1')]
        expected = {target: c.xform(prefix + source, q=True, ws=True, m=True)
                    for source, target in pairs}
        before_output = {n: c.xform(prefix + n, q=True, ws=True, m=True)
                         for n in ('joint1', 'joint2', 'joint3')}
        c.select(prefix + 'armFK_L1', r=True)
        found = mel.eval('EasyGameRig4_0_e8f0c3b3e6300189aca31ae83320ec92("*recalculate_node*")')
        assert found == prefix + 'recalculate_node', found
        mel.eval('kurok_recalculate_system(0);')
        # Pole rotations are locked in the source rig; Easy Rig matches its position only.
        assert all(c.getAttr(prefix + 'elb_L1.r' + axis, lock=True) for axis in 'xyz')
        pose_error = max(abs(a-b) for n, expected_matrix in expected.items() if n != 'elb_L1'
                         for a, b in zip(rigid_matrix(c.xform(prefix+n, q=True, ws=True, m=True)),
                                         rigid_matrix(expected_matrix)))
        pole_error = max(abs(a-b) for a, b in zip(
            c.xform(prefix+'elb_L1', q=True, ws=True, m=True)[12:15], expected['elb_L1'][12:15]))
        assert pole_error < 1e-4, ('pole position mismatch', pole_error)
        output_error = max(abs(a-b) for n, expected_matrix in before_output.items()
                           for a, b in zip(c.xform(prefix+n, q=True, ws=True, m=True), expected_matrix))
        assert pose_error < 1e-4, ('alignment mismatch', pose_error)
        assert output_error < 1e-4, ('output pose changed', output_error)
        assert all(abs(v) < 1e-6 for attr in ('translate', 'rotate')
                   for v in c.getAttr(prefix + 'hand_L1.' + attr)[0])
        keyed = {n: c.keyframe(prefix+n, q=True, keyframeCount=True)
                 for n in ('shldrFK_L1', 'armFK_L1', 'handFK_L1', 'elb_L1', 'hand_L1')}
        assert all(keyed.values()), keyed
        report = {'passed': True, 'discovery_node': found, 'alignment_max_error': pose_error,
                  'pole_position_max_error': pole_error,
                  'output_pose_max_error': output_error, 'key_counts': keyed,
                  'base_checks': base_checks}
    finally:
        c.namespace(setNamespace=':')
        # Only nodes absent before this synchronous test can be removed.
        new_nodes = set(c.ls(long=True)) - before_nodes
        for n in sorted(new_nodes, key=lambda n: n.count('|'), reverse=True):
            if c.objExists(n):
                c.delete(n)
        if ns and c.namespace(exists=ns):
            c.namespace(removeNamespace=ns)
        c.namespace(setNamespace=old_namespace)
        if c.currentTime(q=True) != frame:
            c.currentTime(frame)
        c.autoKeyframe(state=auto)
        c.select(selection, r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True)) == before_nodes, 'Scene node set changed'
        for n, m in before_matrices.items():
            delta = max(abs(a-b) for a, b in zip(c.xform(n, q=True, ws=True, m=True), m))
            assert delta < 1e-6, (n, delta)
        for n, keys in before_keys.items():
            assert (c.keyframe(n, q=True, tc=True), c.keyframe(n, q=True, vc=True)) == keys, n
    report['original_scene_and_animation_preserved'] = True
    return report
