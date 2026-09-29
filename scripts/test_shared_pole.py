"""Shared zero elbow surfaces preserve FK/IK goals, animation and layer edits."""
import math
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import arm_ik,live_edit


def verify():
    before=set(c.ls(l=True));selected=c.ls(sl=True,l=True);time=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);context=c.currentCtx();rig=None
    layers={n:{a:c.animLayer(n,q=True,**{a:True}) for a in ('selected','preferred')} for n in c.ls(type='animLayer')}
    for n in layers:c.animLayer(n,e=True,selected=False,preferred=False)
    c.autoKeyframe(state=False);reports=[]
    try:
        ns='_sharedPole_'+uuid.uuid4().hex[:6];_,parts=fixture(ns,animated=True)
        parts={k:v for k,v in parts.items() if k.startswith('arm')}
        for p in parts.values():p.update(live_alignment=True,space_wrist=True)
        c.currentTime(3);rig=build(parts,namespace=ns,zero_controls=True)
        for p in rig['parts'].values():
            ctrl=p['zero_controls']['pole_locator'];d=arm_ik._data(p['root'])
            for mode in (1,0,1,0):
                c.currentTime(c.currentTime(q=True)+1);c.select(ctrl)
                report=arm_ik.switch(p['root'],mode,key=True)
                assert c.ls(sl=True)==[ctrl]
                assert all(c.getAttr(s+'.lodVisibility') for s in c.listRelatives(ctrl,s=True,f=True))
                assert not any(c.getAttr(s+'.lodVisibility') for s in c.listRelatives(d['controls']['pole'],s=True,f=True))
                c.setToolTo('moveSuperContext');c.autoKeyframe(state=True);c.setKeyframe(ctrl)
                live_edit.before_drag('shared-pole-test')
                c.setAttr(ctrl+'.tx',c.getAttr(ctrl+'.tx')+.25);live_edit.update_drag(force=True)
                held={j:c.xform(j,q=True,ws=True,m=True) for j in p['joints']}
                live_edit.after_drag('shared-pole-test')
                def error():return max(abs(a-b) for j,v in held.items() for a,b in zip(v,c.xform(j,q=True,ws=True,m=True)))
                assert error()<1e-5
                f=c.currentTime(q=True);c.currentTime(f+.5);c.currentTime(f);assert error()<1e-5
                if mode:assert math.dist(c.xform(ctrl,q=True,ws=True,t=True),c.xform(d['controls']['pole'],q=True,ws=True,t=True))<1e-5
                reports.append(report)
            arm_ik.switch(p['root'],1,key=True)
            base={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
            layer=c.animLayer(ns+'_edit',weight=.5,selected=True,preferred=True)
            attrs=[ctrl+'.worldIkTranslate'+a for a in 'XYZ']
            c.animLayer(layer,e=True,attribute=attrs);c.setKeyframe(attrs,animLayer=layer)
            live_edit.before_drag('shared-pole-layer');c.setAttr(ctrl+'.tx',c.getAttr(ctrl+'.tx')+.2)
            live_edit.update_drag(force=True);live_edit.after_drag('shared-pole-layer')
            pose={j:c.xform(j,q=True,ws=True,m=True) for j in p['joints']}
            f=c.currentTime(q=True);c.currentTime(f+.5);c.currentTime(f)
            assert max(abs(a-b) for j,v in pose.items() for a,b in zip(v,c.xform(j,q=True,ws=True,m=True)))<1e-5
            assert all(v==(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n,v in base.items())
            c.animLayer(layer,e=True,selected=False,preferred=False)
        return dict(switches=len(reports),max_switch_error=max(x['max_pose_error'] for x in reports),layers=True)
    finally:
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(l=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.select(selected,r=True) if selected else c.select(cl=True)
        for n,flags in layers.items():c.animLayer(n,e=True,**flags)
        c.autoKeyframe(state=auto);c.setToolTo(context);arm_ik.install()
