"""Regression for baking layered controls without replacing internal FK inputs."""
from unittest.mock import patch

import maya.cmds as cmds

from maya_agent.rigs import live_alignment, live_arm_manual, live_edit, scene_data, zero_channels
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture, remove


def verify():
    prefix = 'armBakeRegression'
    before = set(cmds.ls(long=True))
    rig = None
    try:
        _, parts = fixture(prefix, animated=True)
        parts = {key: opts for key, opts in parts.items() if key.startswith('arm_')}
        for opts in parts.values():
            opts.update(live_alignment=True, space_wrist=True, space_upper_arm=True)
        cmds.currentTime(3)
        rig = build(parts, namespace=prefix, zero_controls=True)
        registered = {}
        destinations = []
        visible = []
        for part in rig['parts'].values():
            data = scene_data.read(part['root'] + '.liveAlignmentData')
            edges = data['protectedInputs']
            for stage in (data['inputs'], data['controls']):
                assert all(stage['end_fk'] + '.translate' + axis in edges for axis in 'XYZ')
            registered.update(edges)
            destinations += list(data['inputs'].values()) + list(data['controls'].values())
            visible += [part['zero_controls'][role] for role in data['inputs']]

        def check_edges():
            for plug, driver in registered.items():
                assert cmds.isConnected(driver, plug) and cmds.getAttr(plug, lock=True), (plug, driver)

        check_edges()
        rogue = cmds.createNode('animCurveTA', name=prefix + '_rogue')
        hidden = next(plug for plug in registered if plug.endswith('handFK_R1.translateX'))
        try:
            cmds.connectAttr(rogue + '.output', hidden, force=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Maya accepted an ordinary forced connection to a protected input')
        cmds.delete(rogue)
        layer = cmds.animLayer(prefix + '_mocap', override=True, passthrough=True)
        for node in visible:
            for attr in live_edit.TR:
                plug = node + '.' + attr
                if cmds.getAttr(plug, lock=True):
                    assert attr.startswith('translate'), plug
                    continue
                cmds.animLayer(layer, e=True, attribute=plug)
                for frame, value in ((1, 0), (3, 5), (5, 2)):
                    cmds.setKeyframe(plug, time=frame, value=value * (.02 if attr.startswith('translate') else 1), animLayer=layer,
                                     noResolve=True, inTangentType='linear', outTangentType='linear')
        samples = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]
        joints = [node for part in rig['parts'].values() for node in part['joints']]

        def pose_samples():
            result = []
            for frame in samples:
                cmds.currentTime(frame)
                result.extend(cmds.xform(node, q=True, ws=True, m=True) for node in joints)
            return result

        expected = pose_samples()
        cmds.bakeResults(visible + destinations, attribute=list(live_edit.TR), time=(1, 5), sampleBy=1,
                         simulation=True, preserveOutsideKeys=True, removeBakedAttributeFromLayer=True)
        cmds.delete(layer)
        check_edges()
        # Bake flattens the editable animation while all hidden inputs still
        # match the original graph. Integer samples must retain the motion.
        baked = pose_samples()
        integer_error = max(abs(a-b) for i,(m,n) in enumerate(zip(expected,baked))
                            if float(samples[i//len(joints)]).is_integer() for a,b in zip(m,n))
        assert integer_error < 1e-5, integer_error
        assert all(cmds.keyframe(node, q=True, at='rotateX', kc=True) >= 5 for node in visible)
        cmds.currentTime(3)
        for part in rig['parts'].values():
            root = part['root']
            for role in ('shoulder_fk', 'middle_fk', 'end_fk'):
                ctrl = part['zero_controls'][role]
                with patch.object(cmds, 'contextInfo', return_value='manipRotate'):
                    gesture = live_arm_manual.begin(root, role)
                    source = scene_data.read(root + '.liveAlignmentData')['inputs'][role]
                    assert gesture['input_locks'] == {p for p in registered if p.startswith(source + '.')}
                    assert all(not cmds.getAttr(plug, lock=True) for plug in gesture['input_locks'])
                    live_arm_manual.finish(gesture, cancel=True)
                    check_edges()
                    gesture = live_arm_manual.begin(root, role)
                    cmds.setAttr(ctrl + '.rotateZ', 4)
                    live_arm_manual.update(gesture, force=True)
                    assert gesture['changed']
                    live_arm_manual.finish(gesture)
                    check_edges()
        root = rig['parts']['arm_L']['root']
        with patch.object(cmds, 'contextInfo', return_value='manipRotate'), patch.object(
                live_arm_manual, 'prepare_native_sample', side_effect=RuntimeError('test isolation error')):
            try:
                live_arm_manual.begin(root, 'shoulder_fk')
            except RuntimeError as error:
                assert str(error) == 'test isolation error'
            else:
                raise AssertionError('Expected an isolation failure')
        check_edges()
        return dict(locked_channels=len(registered), whole_frame_matrix_error=integer_error,
                    bake_and_layer_edit=True, six_gestures_and_cancels=True, failure_restored=True)
    finally:
        if rig:
            remove(rig)
        for node in sorted(set(cmds.ls(long=True)) - before, key=lambda n: n.count('|'), reverse=True):
            if cmds.objExists(node):
                cmds.delete(node)


def verify_body():
    prefix = 'bodyBakeRegression'
    before = set(cmds.ls(long=True))
    rig = None
    try:
        _, parts = fixture(prefix, animated=True)
        cmds.currentTime(3)
        rig = build({'body': parts['body']}, namespace=prefix, zero_controls=True)
        part = rig['parts']['body']
        controls = [part['zero_controls'][role] for role in ('hips', 'chest')]
        registered = {}
        inputs = []
        for control in controls:
            d = scene_data.read(control + '.zeroChannelData')
            assert d['protectInputs']
            registered.update(zero_channels.registered_inputs(d))
            inputs.append(d['source'])
            for t, value in ((1, 0), (3, .3), (5, -.6)):
                for attr in ('translateX', 'rotateZ'):
                    cmds.setKeyframe(control, at=attr, t=t, v=value)

        def pose():
            values = []
            for t in range(1, 6):
                cmds.currentTime(t)
                values.extend(cmds.xform(node, q=True, ws=True, m=True) for node in part['joints'])
            return values

        expected = pose()
        cmds.bakeResults(controls + inputs, at=list(live_edit.TR), t=(1, 5), simulation=True)
        matrix_error = max(abs(a-b) for p,q in zip(expected,pose()) for a,b in zip(p,q))
        assert matrix_error < 1e-5, matrix_error
        for control in controls:
            for mode, axis in (('manipMove', 'translateX'), ('manipRotate', 'rotateZ')):
                cmds.currentTime(3)
                with patch.object(cmds, 'contextInfo', return_value=mode):
                    entry = zero_channels.begin(control)
                    cmds.setAttr(control + '.' + axis, cmds.getAttr(control + '.' + axis) + .3)
                    live_arm_manual.update(entry, force=True)
                    assert entry['changed']
                    live_arm_manual.finish(entry)
        for plug, driver in registered.items():
            assert cmds.isConnected(driver, plug) and cmds.getAttr(plug, lock=True), plug
        return dict(locked_channels=len(registered), bake_pose_error=matrix_error, hips_and_chest_move_rotate=True)
    finally:
        if rig:
            remove(rig)
        for node in sorted(set(cmds.ls(long=True)) - before, key=lambda n: n.count('|'), reverse=True):
            if cmds.objExists(node):
                cmds.delete(node)


def verify_feet():
    prefix = 'footBakeRegression'
    before = set(cmds.ls(long=True))
    rig = None
    try:
        _, parts = fixture(prefix, animated=True)
        parts = {key: opts for key, opts in parts.items() if key.startswith('leg_')}
        for opts in parts.values():
            opts.update(live_alignment=True, space_foot=True, space_knee=True)
        cmds.currentTime(3)
        rig = build(parts, namespace=prefix, zero_controls=True)
        controls, hidden, edges, ankles = [], [], {}, []
        for part in rig['parts'].values():
            data = scene_data.read(part['root'] + '.liveAlignmentData')
            edges.update(live_alignment.protected_inputs(data))
            ctrl = part['zero_controls']['foot']
            controls.append(ctrl)
            hidden.extend((data['inputs']['foot'], data['controls']['foot']))
            ankles.append(part['joints'][2])
            assert all(n + '.' + a in edges for n in hidden[-2:] for a in live_edit.TR)
        cmds.bakeResults(controls + hidden, attribute=list(live_edit.TR), time=(1,5), simulation=True)
        assert all(cmds.isConnected(source, plug) and cmds.getAttr(plug, lock=True) for plug,source in edges.items())
        layer = cmds.animLayer(prefix + '_edit', weight=.5, override=True, selected=True, preferred=True)
        for ctrl in controls:
            cmds.animLayer(layer, e=True, attribute=[ctrl + '.' + a for a in live_edit.TR])
        max_error = 0.0
        for ctrl, ankle in zip(controls, ankles):
            for context, attr, delta in (('moveSuperContext', 'translateY', .15), ('RotateSuperContext', 'rotateX', 3)):
                cmds.currentTime(3)
                cmds.select(ctrl, r=True)
                cmds.setToolTo(context)
                cmds.autoKeyframe(state=True)
                start = cmds.xform(ankle, q=True, ws=True, m=True)
                live_edit.before_drag('foot-layer-regression')
                assert live_edit._gesture['anim_layer'] == layer
                cmds.setAttr(ctrl + '.' + attr, cmds.getAttr(ctrl + '.' + attr) + delta)
                live_edit.update_drag(force=True)
                moved = cmds.xform(ankle, q=True, ws=True, m=True)
                assert max(abs(a-b) for a,b in zip(start, moved)) > 1e-4, attr
                live_edit.after_drag('foot-layer-regression')
                released = cmds.xform(ankle, q=True, ws=True, m=True)
                cmds.currentTime(4)
                cmds.currentTime(3)
                replayed = cmds.xform(ankle, q=True, ws=True, m=True)
                error = max(abs(a-b) for sample in (released,replayed) for a,b in zip(moved,sample))
                max_error = max(max_error,error)
                assert error < 1e-5, (ctrl,attr,error)
                assert all(cmds.isConnected(source, plug) and cmds.getAttr(plug, lock=True) for plug,source in edges.items())
        return dict(locked_channels=len(edges), layered_moves_and_rotations=4, max_release_or_replay_error=max_error)
    finally:
        if live_edit._gesture:
            for entry in reversed(live_edit._gesture.get('arm_gestures', [])):
                live_arm_manual.finish(entry, cancel=True)
            live_edit.after_drag('foot-layer-regression')
        cmds.autoKeyframe(state=False)
        if rig:
            remove(rig)
        for node in sorted(set(cmds.ls(long=True)) - before, key=lambda n: n.count('|'), reverse=True):
            if cmds.objExists(node):
                cmds.delete(node)
