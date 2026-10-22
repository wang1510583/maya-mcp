"""Disposable real-Maya regression; preserve the open scene and its animation."""
import json
import math
import runpy
import uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om


def _matrix(node):
    return om.MMatrix(c.xform(node, q=True, ws=True, matrix=True))


def _error(a, b):
    return max(abs(x-y) for x,y in zip(a,b))


def _curves(nodes):
    return {n: (c.keyframe(n,q=True,tc=True), c.keyframe(n,q=True,vc=True),
                c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True),
                c.listConnections(n,s=True,d=True,p=True,c=True)) for n in nodes if c.objExists(n)}


def run(animated=False):
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import external_constraints as external, arm_ik, foot_space, live_edit
    suite = runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before = set(c.ls(uuid=True)); selected = c.ls(sl=True,long=True) or []; frame = c.currentTime(q=True)
    scene=c.file(q=True,sn=True); modified=c.file(q=True,modified=True); auto=c.autoKeyframe(q=True,state=True)
    original_curves=_curves(c.ls(type='animCurve') or [])
    prefix = '_externalTest_' + uuid.uuid4().hex[:8]; rig=None; fixture=None; rows=[]
    c.autoKeyframe(state=False)
    try:
        fixture,parts=suite['fixture'](prefix,animated,shoulders=True)
        for key,p in parts.items():
            if key.startswith('arm'):p.update(live_alignment=True,space_wrist=True,space_upper_arm=True)
            if key.startswith('leg'):p.update(live_alignment=True,space_foot=True,space_knee=True)
        c.currentTime(1); rig=build(parts,namespace=prefix,zero_controls=True)
        watched=[n for part in rig['parts'].values() for n in part.get('joints',[])]
        for side in ('L','R'):
            for key,role,mode in [('arm_'+side,'end_fk',0),('arm_'+side,'end_fk',1),('leg_'+side,'foot',0),('leg_'+side,'foot',1)]:
                part=rig['parts'][key]; ctrl=part['zero_controls'][role]
                c.currentTime(1)
                if key.startswith('arm'): arm_ik.switch(part['root'],mode,key=False)
                else:foot_space.switch(part['root'],mode,key=False)
                for kind in ('parent','point','orient'):
                    goal=c.createNode('transform',name=prefix+':goal')
                    c.xform(goal,ws=True,matrix=list(live_edit._frame(ctrl)))
                    source=external.resolve(ctrl)['source']; original_opm=c.connectionInfo(source+'.offsetParentMatrix',sfd=True)
                    goal0=_matrix(goal); source0=live_edit._frame(source)
                    poses={n:_matrix(n) for n in watched}; curves=_curves(c.ls(type='animCurve') or [])
                    result=external.attach(ctrl,goal,kind)
                    assert _curves(curves)==curves,'Adding a constraint modified original curves'
                    worst=0.0
                    for tx,ty,tz,rx,ry,rz in ((.25,-.1,.15,0,0,0),(0,0,0,8,-12,5),(-.1,.2,.1,-7,11,4)):
                        # An independent world transform, including original target orientation.
                        delta=om.MTransformationMatrix();delta.setTranslation(om.MVector(tx,ty,tz),om.MSpace.kTransform)
                        delta.setRotation(om.MEulerRotation(*map(math.radians,(rx,ry,rz))))
                        # Rotate about the target's starting pivot, then translate in world.
                        pivot=om.MMatrix();pivot[12]=goal0[12];pivot[13]=goal0[13];pivot[14]=goal0[14]
                        desired=goal0*pivot.inverse()*delta.asMatrix()*pivot
                        c.xform(goal,ws=True,matrix=list(desired))
                        assert not c.cycleCheck(all=True,list=True),'External constraint introduced cycle'
                        if kind=='parent':
                            expected=source0*goal0.inverse()*desired
                            worst=max(worst,_error(live_edit._frame(source),expected))
                            assert worst<1e-5,(key,mode,kind,worst)
                        if kind=='point':
                            actual=list(live_edit._frame(source));start=list(source0)
                            assert max(abs(actual[i]-start[i]) for i in range(12))<1e-5
                            expected=[start[12+i]+desired[12+i]-goal0[12+i] for i in range(3)]
                            assert max(abs(actual[12+i]-expected[i]) for i in range(3))<1e-5
                        if kind=='orient':
                            assert max(abs(live_edit._frame(source)[12+i]-source0[12+i]) for i in range(3))<1e-5
                    assert _curves(curves)==curves,'Following changed original animation'
                    external.remove(ctrl)
                    assert c.connectionInfo(source+'.offsetParentMatrix',sfd=True)==original_opm
                    restore=max(_error(_matrix(n),p) for n,p in poses.items())
                    assert restore<1e-4,(key,mode,'remove',restore)
                    assert _curves(curves)==curves
                    c.delete(goal)
                    rows.append(dict(part=key,mode=mode,kind=kind,input_error=worst,restored_error=restore))
        # Reject actual feedback and leave all original connections intact.
        ctrl=rig['parts']['leg_L']['zero_controls']['foot']
        source=external.resolve(ctrl)['source'];old=c.connectionInfo(source+'.offsetParentMatrix',sfd=True)
        nodes=set(c.ls(uuid=True))
        try:external.attach(ctrl,rig['parts']['leg_L']['joints'][2])
        except ValueError as exc:assert '循环' in str(exc)
        else:raise AssertionError('Accepted solver feedback')
        assert set(c.ls(uuid=True))==nodes
        assert c.connectionInfo(source+'.offsetParentMatrix',sfd=True)==old
        assert not c.cycleCheck(all=True,list=True)
        # Animated target, fractional frames, original curves and complete restoration.
        part=rig['parts']['arm_L'];arm_ik.switch(part['root'],1,key=False)
        ctrl=part['zero_controls']['end_fk'];source=external.resolve(ctrl)['source']
        base={};times=(1,1.25,2,2.5,3,4.75,5)
        for t in times:
            c.currentTime(t);base[t]={n:_matrix(n) for n in watched}
        c.currentTime(1)
        goal=c.createNode('transform',name=prefix+':animatedGoal');c.xform(goal,ws=True,matrix=list(live_edit._frame(ctrl)))
        curves=_curves(c.ls(type='animCurve') or []);external.attach(ctrl,goal)
        for attr,delta in [('translateX',.35),('rotateY',12)]:
            v=c.getAttr(goal+'.'+attr)
            for t,factor in [(1,0),(3,1),(5,-.4)]:c.setKeyframe(goal,at=attr,t=t,v=v+delta*factor)
        for t in times:
            c.currentTime(t)
            assert all(math.isfinite(v) for n in watched for v in _matrix(n))
            assert not c.cycleCheck(all=True,list=True)
        assert _curves(curves)==curves
        external.remove(ctrl)
        for t in times:
            c.currentTime(t)
            assert max(_error(_matrix(n),m) for n,m in base[t].items())<1e-4
        c.delete(goal)
        if not animated:
            # Exercise the same W/E gesture path used by the viewport, with the
            # target moved so that the new input offset is not the identity.
            from maya_agent.rigs import arm_ik_shared,live_arm_manual,zero_channels
            for key,role in [('arm_L','end_fk'),('leg_L','foot')]:
                part=rig['parts'][key];ctrl=part['zero_controls'][role]
                if key.startswith('arm'):arm_ik.switch(part['root'],1,key=False)
                goal=c.createNode('transform',name=prefix+':gestureGoal')
                c.xform(goal,ws=True,matrix=list(live_edit._frame(ctrl)))
                external.attach(ctrl,goal);c.setAttr(goal+'.translateX',c.getAttr(goal+'.translateX')+.5)
                c.setAttr(goal+'.rotateY',c.getAttr(goal+'.rotateY')+15)
                entry=arm_ik_shared.begin(part['root']) if key.startswith('arm') else zero_channels.begin(ctrl)
                try:
                    c.setAttr(entry['proxy']+'.translateX',c.getAttr(entry['proxy']+'.translateX')+.12)
                    c.setAttr(entry['proxy']+'.rotateY',c.getAttr(entry['proxy']+'.rotateY')+7)
                    local=om.MTransformationMatrix(entry['local']);local.setTranslation(om.MVector(*c.getAttr(entry['proxy']+'.translate')[0]),om.MSpace.kTransform)
                    local.setRotation(om.MEulerRotation(*[math.radians(v) for v in c.getAttr(entry['proxy']+'.rotate')[0]],c.getAttr(entry['proxy']+'.rotateOrder')))
                    expected=entry['input_basis']*local.asMatrix()*entry['parent']
                    live_arm_manual.update(entry,force=True)
                    error=_error(live_edit._frame(entry['source']),expected)
                    assert error<1e-5,('constrained viewport gesture',key,error)
                finally:live_arm_manual.finish(entry,cancel=True)
                poses={n:_matrix(n) for n in part['joints']}
                for new_mode in (0,1):
                    if key.startswith('arm'):arm_ik.switch(part['root'],new_mode,key=False)
                    else:foot_space.switch(part['root'],new_mode,key=False)
                    error=max(_error(_matrix(n),m) for n,m in poses.items())
                    assert error<1e-4,('constrained space switch',key,new_mode,error)
                external.remove(ctrl);c.delete(goal)
        return dict(passed=True,animated=animated,cases=rows,feedback_rejected=True,fractional_playback=True)
    finally:
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        # Animation-transfer backups can retain disconnected fixture curves.
        # Only remove new UUIDs owned by this test, never preexisting curves.
        for uid in set(c.ls(uuid=True))-before:
            nodes=c.ls(uid,long=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):
                c.delete(nodes[0])
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selected,replace=True) if selected else c.select(clear=True)
        assert set(c.ls(uuid=True))==before,'Scene nodes changed after fixture cleanup'
        assert _curves(original_curves)==original_curves,'User animation changed'
        assert c.file(q=True,sn=True)==scene
        c.file(modified=modified)


def lifecycle():
    """Run over the raw Maya bridge, without an enclosing tool undo chunk."""
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import external_constraints as external,arm_ik
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(uuid=True)); selected=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    prefix='_externalUndo_'+uuid.uuid4().hex[:8];rig=None;fixture=None
    c.autoKeyframe(state=False)
    try:
        fixture,parts=suite['fixture'](prefix,False)
        parts={k:p for k,p in parts.items() if k in ('arm_L','leg_L')}
        for p in parts.values():p.update(live_alignment=True,space_wrist=True)
        rig=build(parts,namespace=prefix,zero_controls=True)
        for key,role in [('arm_L','end_fk'),('leg_L','foot')]:
            part=rig['parts'][key];ctrl=part['zero_controls'][role]
            if key.startswith('arm'):arm_ik.switch(part['root'],1,key=False)
            goal=c.createNode('transform',name=prefix+':goal');c.xform(goal,ws=True,matrix=list(_matrix(ctrl)))
            source=external.resolve(ctrl)['source'];baseline=_matrix(source)
            result=external.attach(ctrl,goal)
            assert c.undoInfo(q=True,undoName=True)=='AttachExternalHandFootConstraint', c.undoInfo(q=True,undoName=True)
            c.undo();assert external.registry(ctrl) is None
            assert _error(_matrix(source),baseline)<1e-5
            c.redo();assert external.registry(ctrl)
            c.setAttr(goal+'.translateX',c.getAttr(goal+'.translateX')+.75);moved=_matrix(source)
            assert _error(moved,baseline)>.5
            external.remove(ctrl)
            assert _error(_matrix(source),baseline)<1e-5
            assert c.undoInfo(q=True,undoName=True)=='RemoveExternalHandFootConstraint', c.undoInfo(q=True,undoName=True)
            c.undo();assert external.registry(ctrl)
            assert _error(_matrix(source),moved)<1e-5
            c.redo();assert external.registry(ctrl) is None
            assert _error(_matrix(source),baseline)<1e-5
            # UUID/message ownership survives target renaming and target deletion.
            result=external.attach(ctrl,goal);goal=c.rename(goal,prefix+':renamedGoal')
            assert external._link(result['registry'],'target')==goal
            c.delete(goal);external.remove(ctrl)
            assert _error(_matrix(source),baseline)<1e-5
            assert not c.cycleCheck(all=True,list=True)
        return dict(passed=True,undo_redo=True,target_rename_delete=True)
    finally:
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selected,replace=True) if selected else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(uuid=True))==before
