"""Real Maya default-menu + native Delete regression, in disposable namespaces.

Run run() from a Qt timer, outside the enclosing Maya MCP undo chunk.
"""
import json
import runpy
import uuid
from pathlib import Path
import maya.cmds as c
import maya.mel as mel
import maya.api.OpenMaya as om


def menu(kind, maintain=True, skip=False, offset=False):
    if kind == 'parent':
        args = [int(maintain), 0, 0, int(skip), 0, 0, 0, 0, 1, '', 1]
    else:
        args = [int(maintain), 0.15 if offset else 0, 0, 0, 0, int(skip), 0, 1, '', 1]
    # This is the entry called by both menu Apply and the option-box Apply.
    mel.eval('doCreate%sConstraintArgList "1" {%s};' %
             (kind.title(), ','.join(json.dumps(str(v)) for v in args)))


def matrix(n):
    return om.MMatrix(c.xform(n, q=True, ws=True, matrix=True))


def error(a, b):
    return max(abs(x-y) for x,y in zip(a,b))


def run(animated=False, exhaustive=False, arm_roles=('end_fk',), only_arms=False):
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import external_constraints as external, native_constraints as native, arm_ik, foot_space, live_edit
    suite = runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    previous = runpy.run_path(str(Path(__file__).with_name('test_external_constraints_live.py')))
    native.install()
    before = set(c.ls(uuid=True)); selected = c.ls(sl=True, long=True) or []
    frame = c.currentTime(q=True); auto = c.autoKeyframe(q=True, state=True)
    scene = c.file(q=True, sn=True); modified = c.file(q=True, modified=True)
    curves = previous['_curves'](c.ls(type='animCurve') or [])
    prefix = '_nativeTest_' + uuid.uuid4().hex[:8]
    rig = fixture = None; goals = []; rows = []
    c.autoKeyframe(state=False)
    try:
        fixture, parts = suite['fixture'](prefix, animated)
        if not exhaustive:
            parts = {k:v for k,v in parts.items() if k in ('arm_L', 'leg_L')}
        for key, part in parts.items():
            if key.startswith('arm'):
                part.update(live_alignment=True, space_wrist=True, space_upper_arm=True)
            if key.startswith('leg'):
                part.update(live_alignment=True, space_foot=True, space_knee=True)
        c.currentTime(1)
        rig = build(parts, namespace=prefix, zero_controls=True)
        cases=[(key,part,role) for key,part in rig['parts'].items()
               for role in (arm_roles if key.startswith('arm_') else ('foot',) if key.startswith('leg_') and not only_arms else ())]
        for key, part, role in cases:
            ctrl = part['zero_controls'][role]
            for mode in (0, 1):
                c.currentTime(1)
                switch = arm_ik.switch if key.startswith('arm') else foot_space.switch
                switch(part['root'], mode, key=False)
                for kind in ('parent', 'point', 'orient'):
                    for maintain in ((True, False) if exhaustive else (True,)):
                        goal = c.createNode('transform', name=prefix+':goal'); goals.append(goal)
                        c.xform(goal, ws=True, matrix=list(live_edit._frame(ctrl)))
                        c.setAttr(goal+'.tx', c.getAttr(goal+'.tx')+.2)
                        source = external.resolve(ctrl)['source']
                        baseline = matrix(source)
                        initial = {n: matrix(n) for n in part['joints']}
                        protected = previous['_curves'](c.ls(type='animCurve') or [])
                        c.select([goal, ctrl], r=True)
                        menu(kind, maintain)
                        owner = external.registry(ctrl)
                        assert owner, ('menu did not attach', key, mode, kind)
                        constraint = external._link(owner, 'constraint')
                        anchor = external._link(owner, 'anchor')
                        helper_nodes = [owner, anchor, external._link(owner, 'matrix')]
                        assert external._same((c.listRelatives(constraint, parent=True) or [None])[0], ctrl)
                        assert not c.cycleCheck(all=True, list=True)
                        if maintain:
                            assert max(error(matrix(n), m) for n,m in initial.items()) < 1e-4
                        c.undo()
                        assert not external.registry(ctrl), 'Native creation undo left a registry'
                        assert error(matrix(source), baseline) < 1e-5
                        c.redo()
                        assert external.registry(ctrl), 'Native creation redo lost registry'
                        c.setAttr(goal+'.tx', c.getAttr(goal+'.tx')+.35)
                        c.setAttr(goal+'.ry', 12)
                        moved = matrix(source)
                        assert error(moved, baseline) > .001
                        if mode==0 and role in ('shoulder_fk','middle_fk') and kind=='orient':
                            assert max(error(matrix(n),m) for n,m in initial.items())>1e-4, 'FK input did not move the solved arm'
                        c.delete(constraint)
                        assert not external.registry(ctrl), 'Native deletion left registry'
                        assert not any(c.objExists(n) for n in helper_nodes), 'Native deletion left helpers'
                        assert error(matrix(source), baseline) < 1e-5
                        c.undo()
                        assert external.registry(ctrl), 'Delete undo did not restore registry'
                        assert error(matrix(source), moved) < 1e-5
                        c.redo()
                        assert not external.registry(ctrl), 'Delete redo left registry'
                        assert error(matrix(source), baseline) < 1e-5
                        assert previous['_curves'](protected) == protected, 'Existing curves changed'
                        if animated:
                            for t in (1, 1.25, 2.5, 4.75, 5):
                                c.currentTime(t)
                                assert not c.cycleCheck(all=True, list=True)
                            c.currentTime(1)
                        c.delete(goal); goals.remove(goal)
                        rows.append((key, role, mode, kind, maintain))
        extras(rig, prefix, goals)
        # Ordinary Maya objects must still use the unmodified native procedure.
        a = c.createNode('transform', name=prefix+':ordinaryTarget'); goals.append(a)
        b = c.createNode('transform', name=prefix+':ordinaryChild'); goals.append(b)
        for kind in ('parent', 'point', 'orient'):
            c.select([a,b], r=True); menu(kind)
            nodes = c.listRelatives(b, type=kind+'Constraint') or []
            assert len(nodes) == 1 and not external.registry(b)
            c.delete(nodes)
        return dict(passed=True, animated=animated, cases=rows, ordinary_passthrough=True,
                    native_creation_undo_redo=True, native_delete_undo_redo=True,
                    multiple_targets_skip_offset=True, feedback_rejected=True, callback_refresh=True)
    finally:
        # Release native layers before the suite removes their whole rig.
        for owner in c.ls(prefix+'*:*.'+external.DATA, objectsOnly=True) or []:
            external.remove(owner)
        if rig:
            suite['remove'](rig)
        if fixture and c.objExists(fixture):
            c.delete(fixture)
        for n in goals:
            if c.objExists(n):
                c.delete(n)
        for uid in set(c.ls(uuid=True))-before:
            nodes = c.ls(uid, long=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):
                c.delete(nodes[0])
        c.currentTime(frame); c.autoKeyframe(state=auto)
        c.select(selected, r=True) if selected else c.select(clear=True)
        assert set(c.ls(uuid=True)) == before, 'Test left scene nodes'
        assert previous['_curves'](curves) == curves, 'User animation changed'
        assert c.file(q=True, sn=True) == scene
        c.file(modified=modified)


def extras(rig, prefix, goals):
    """Compare options with an independent native Maya constraint reference."""
    from maya_agent.rigs import external_constraints as external, native_constraints as native, arm_ik, live_edit
    part = rig['parts']['arm_L']; ctrl = part['zero_controls']['end_fk']
    arm_ik.switch(part['root'], 1, key=False)
    source = external.resolve(ctrl)['source']
    for kind in ('parent', 'point', 'orient'):
        target = c.createNode('transform', name=prefix+':optionTarget'); goals.append(target)
        target2 = c.createNode('transform', name=prefix+':optionTarget2'); goals.append(target2)
        reference = c.createNode('transform', name=prefix+':optionReference'); goals.append(reference)
        frame = live_edit._frame(ctrl)
        c.xform(reference, ws=True, matrix=list(frame))
        c.xform(target, ws=True, matrix=list(frame)); c.setAttr(target+'.tx',c.getAttr(target+'.tx')+.3)
        c.xform(target2, ws=True, matrix=list(frame)); c.setAttr(target2+'.ty',c.getAttr(target2+'.ty')+.2)
        options = dict(maintainOffset=False, weight=1)
        if kind == 'parent':
            options.update(skipTranslate=['y'], decompRotationToChild=False)
        else:
            options.update(skip=['y'], offset=[.15,0,0])
        reference_constraint = getattr(c,kind+'Constraint')(target,target2,reference,**options)[0]
        c.select([target, target2, ctrl], r=True)
        menu(kind, maintain=False, skip=True, offset=True)
        owner = external.registry(ctrl); anchor = external._link(owner,'anchor')
        constraint = external._link(owner,'constraint')
        assert len(getattr(c,kind+'Constraint')(constraint,q=True,targetList=True)) == 2
        for tx,ry in ((.5,13),(-.2,-7)):
            c.setAttr(target+'.tx',c.getAttr(target+'.tx')+tx); c.setAttr(target+'.ry',ry)
            assert error(matrix(reference),matrix(anchor)) < 1e-5, ('native options differ',kind)
        # Simulate callback re-registration after a fresh plugin/scene load.
        for handle,callback in native._watches.values():
            om.MMessage.removeCallback(callback)
        native._watches.clear(); native.refresh()
        c.delete(constraint)
        assert not external.registry(ctrl)
        for n in (reference, target, target2):
            c.delete(n); goals.remove(n)
    # Genuine feedback must fail and leave the exact input graph intact.
    before = set(c.ls(uuid=True)); pose = matrix(source)
    c.select([part['joints'][-1], ctrl], r=True)
    try:
        menu('parent')
    except RuntimeError:
        pass
    else:
        raise AssertionError('Feedback target accepted')
    assert set(c.ls(uuid=True)) == before and error(matrix(source),pose)<1e-5
    assert not c.cycleCheck(all=True,list=True)


def gestures():
    """Reuse established input/gesture/space tests with the native adapter."""
    from maya_agent.rigs import external_constraints as external
    original = external.attach
    def attach(control, target, kind='parent', **kwargs):
        return original(control, target, kind, native=True, **kwargs)
    external.attach = attach
    try:
        suite = runpy.run_path(str(Path(__file__).with_name('test_external_constraints_live.py')))
        return suite['run'](animated=False)
    finally:
        external.attach = original


def arm_interaction(gestures=True):
    """Animated FK arms: simultaneous constraints, mouse editing and restore."""
    import math
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import external_constraints as external, live_edit, live_arm_manual, arm_ik
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    old=runpy.run_path(str(Path(__file__).with_name('test_external_constraints_live.py')))
    before=set(c.ls(uuid=True));selection=c.ls(sl=True,l=True) or []
    modified=c.file(q=True,modified=True);frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    original_curves=old['_curves'](c.ls(type='animCurve') or [])
    prefix='_armConstraint_'+uuid.uuid4().hex[:8];rig=fixture=None;goals=[]
    c.autoKeyframe(state=False)
    try:
        fixture,parts=suite['fixture'](prefix,True)
        parts={k:v for k,v in parts.items() if k.startswith('arm')}
        for part in parts.values():part.update(live_alignment=True,space_wrist=True,space_upper_arm=True)
        c.currentTime(1);rig=build(parts,namespace=prefix,zero_controls=True)
        for part in rig['parts'].values():
            arm_ik.switch(part['root'],0,key=False)
            joints=part['joints'];times=(1,1.25,2.5,3,4.75,5);baseline={}
            for t in times:
                c.currentTime(t);baseline[t]={n:matrix(n) for n in joints}
            for t in times:
                c.currentTime(t)
                assert max(error(matrix(n),m) for n,m in baseline[t].items())<1e-4, ('baseline repeat before constraint',t)
            c.currentTime(1)
            curves=old['_curves'](c.ls(type='animCurve') or [])
            recalc=part['namespace']+':recalculate_node'
            links=c.listConnections(recalc,s=True,d=True,p=True,c=True)
            controls=[]
            for role in ('shoulder_fk','middle_fk'):
                ctrl=part['zero_controls'][role];controls.append(ctrl)
                goal=c.createNode('transform',name=prefix+':gestureGoal');goals.append(goal)
                c.xform(goal,ws=True,matrix=list(live_edit._frame(ctrl)))
                c.select([goal,ctrl],r=True);menu('parent')
                # First preserve a second, simultaneous parent constraint.
            for goal in goals:
                c.setAttr(goal+'.tx',c.getAttr(goal+'.tx')+.2)
                c.setAttr(goal+'.ry',11)
            for role in (('shoulder_fk','middle_fk') if gestures else ()):
                entry=live_arm_manual.begin(part['root'],role)
                try:
                    proxy=entry['proxy']
                    c.setAttr(proxy+'.tx',c.getAttr(proxy+'.tx')+.08)
                    c.setAttr(proxy+'.ry',c.getAttr(proxy+'.ry')+5)
                    local=om.MTransformationMatrix(entry['local'])
                    local.setTranslation(om.MVector(*c.getAttr(proxy+'.translate')[0]),om.MSpace.kTransform)
                    local.setRotation(om.MEulerRotation(*[math.radians(v) for v in c.getAttr(proxy+'.rotate')[0]],c.getAttr(proxy+'.rotateOrder')))
                    expected=entry.get('input_basis',om.MMatrix())*local.asMatrix()*entry['parent']
                    live_arm_manual.update(entry,force=True)
                    assert error(live_edit._frame(entry['source']),expected)<1e-5,('gesture',role)
                finally:live_arm_manual.finish(entry,cancel=True)
            for goal in goals:
                for t,v in ((1,0),(3,.3),(5,-.2)):
                    c.setKeyframe(goal,at='tz',t=t,v=v)
            for t in times:
                c.currentTime(t)
                assert not c.cycleCheck(all=True,list=True)
                assert all(math.isfinite(v) for n in joints for v in matrix(n))
            for ctrl in reversed(controls):
                owner=external.registry(ctrl);constraint=external._link(owner,'constraint')
                constrained={n:matrix(n) for n in joints}
                c.delete(constraint)
                assert not external.registry(ctrl), ('delete not restored',ctrl,constraint)
                restored={n:matrix(n) for n in joints}
                c.undo()
                assert external.registry(ctrl)
                assert max(error(matrix(n),m) for n,m in constrained.items())<1e-5
                c.redo()
                assert not external.registry(ctrl)
                assert max(error(matrix(n),m) for n,m in restored.items())<1e-5
            for t in times:
                c.currentTime(t)
                delta=max(error(matrix(n),m) for n,m in baseline[t].items())
                assert delta<1e-4, (part['namespace'],t,delta)
            assert old['_curves'](curves)==curves
            assert c.listConnections(recalc,s=True,d=True,p=True,c=True)==links
            for goal in goals:c.delete(goal)
            goals.clear();c.currentTime(1)
        return dict(passed=True,animated_both_sides=True,simultaneous_upper_forearm=True,
                    gesture_move_rotate=gestures,fractional_restore=True,easy_rig_links_preserved=True,
                    simultaneous_delete_undo_redo=True)
    finally:
        for owner in c.ls(prefix+'*:*.'+external.DATA,objectsOnly=True) or []:external.remove(owner)
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        for n in goals:
            if c.objExists(n):c.delete(n)
        for uid in set(c.ls(uuid=True))-before:
            nodes=c.ls(uid,l=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):c.delete(nodes[0])
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(uuid=True))==before
        assert old['_curves'](original_curves)==original_curves
        c.file(modified=modified)
