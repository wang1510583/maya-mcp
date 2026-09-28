"""Actual single-control rotation keys, subframes and subsequent edit reuse."""
import math,uuid
import maya.cmds as c
import maya.api.OpenMaya as om
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_edit,live_alignment,live_rotation


def verify(global_space=False,role='middle_fk'):
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();rig=None;reports=[]
    try:
        c.autoKeyframe(state=False)
        prefix='_armRotateOnly_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,True)
        for p in parts.values():p.update(space_upper_arm=True,space_wrist=True)
        c.currentTime(5);rig=build({k:p for k,p in parts.items() if k.startswith('arm')},namespace=prefix)
        for key,p in rig['parts'].items():
            d=live_alignment.enable(p,'arm');ctrl=d['controls'][role];wrist=d['controls']['end_fk']
            pole=p['namespace']+':elb_'+p['side']+'1';hand=p['namespace']+':hand_'+p['side']+'1'
            c.setAttr(wrist+'.global',int(global_space))
            c.move(-.6 if p['side']=='L' else .6,.5,1,wrist,r=True,ws=True)
            nodes=list(d['controls'].values())+[pole,hand]
            for node in nodes:
                for attr in live_edit.TR:
                    plug=node+'.'+attr
                    if c.getAttr(plug,lock=True):continue
                    value=c.getAttr(plug)
                    for f in (6,12):c.setKeyframe(plug,time=f,value=value)
            companions=[n+'.'+a for n in nodes if n!=ctrl for a in live_edit.TR]
            saved=live_edit._snapshot(companions)[1]
            c.currentTime(6);c.setToolTo('RotateSuperContext');c.select(ctrl)
            owned=set(c.ls(long=True))
            live_edit.before_drag('test');live_edit.after_drag('test')
            assert owned==set(c.ls(long=True)),'Click leaked rotation references'
            elbow=c.xform(p['joints'][1],q=True,ws=True,t=True)
            c.autoKeyframe(state=True)
            max_error=0
            for f,angle in ((6,17),(12,-13)):
                c.currentTime(f)
                locked_wrist=c.xform(p['joints'][2],q=True,ws=True,t=True)
                expected=None
                if not global_space:
                    frame=om.MMatrix(c.xform(ctrl,q=True,ws=True,m=True))
                    delta=frame.inverse()*om.MEulerRotation(0,0,math.radians(angle)).asMatrix()*frame
                    expected={n:list(om.MMatrix(c.xform(n,q=True,ws=True,m=True))*(delta if role=='shoulder_fk' or n!=p['joints'][0] else om.MMatrix())) for n in p['joints']}
                live_edit.before_drag('test');c.rotate(0,0,angle,ctrl,r=True,os=True);live_edit.after_drag('test')
                if expected:
                    err=max(abs(a-b) for n,m in expected.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
                    max_error=max(max_error,err)
                else:assert math.dist(locked_wrist,c.xform(p['joints'][2],q=True,ws=True,t=True))<1e-5
            assert saved==live_edit._snapshot(companions)[1],'Other controllers were keyed'
            hold=0
            if not global_space and role=='middle_fk':
                for i in range(25):
                    c.currentTime(6+i*.25)
                    hold=max(hold,math.dist(elbow,c.xform(p['joints'][1],q=True,ws=True,t=True)))
                assert hold<1e-5,(hold,{a:[c.getAttr(ctrl+'.'+a,time=f) for f in (6,12)] for a in live_edit.TR+live_rotation.PIVOTS})
            assert max_error<1e-5,(key,max_error)
            # Explicit full alignment and Move must still understand the new frame.
            c.currentTime(9);pose={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
            snap=live_edit.prepare(p['root'])
            assert max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-5
            live_edit._restore(snap)
            # Changing the wrist invalidates the old input frame. A new frame
            # must retain ALL old motion, not just its creation-time pose.
            if not global_space:
                c.autoKeyframe(state=False)
                c.move(.3,-.15,.2,wrist,r=True,ws=True)
                c.setKeyframe(wrist,at=['translateX','translateY','translateZ'],time=9)
                baseline={}
                for f in [6+i*.25 for i in range(25)]:
                    c.currentTime(f);baseline[f]={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
                c.currentTime(9)
                entry=live_rotation.install(p['root'],role)
                assert entry is not None,'Expected a changed solved frame'
                live_rotation.rollback(entry)
                for f,pose in baseline.items():
                    c.currentTime(f)
                    assert max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-5
                c.currentTime(9)
                saved_again=live_edit._snapshot(companions)[1]
                c.autoKeyframe(state=True)
                live_edit.before_drag('test');c.rotate(0,0,5,ctrl,r=True,os=True);live_edit.after_drag('test')
                assert saved_again==live_edit._snapshot(companions)[1]
            assert not c.objExists(d['inputs'][role]+'.liveRotationData')
            assert not (c.ls(p['namespace']+':rotation_*') or []),'Gesture nodes survived release'
            reports.append(dict(part=key,role=role,global_space=global_space,motion_error=max_error if not global_space else None,
                subframe_elbow_error=hold if not global_space and role=='middle_fk' else None,companion_keys_preserved=True,reframe_preserves_animation=not global_space))
            c.autoKeyframe(state=False)
        return reports
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(sel,r=True) if sel else c.select(cl=True)
