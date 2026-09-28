"""Multi-key edits, retiming, deletion, and direct animation ownership in Maya."""
import math, uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture, remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_edit, live_alignment, live_rotation


def verify():
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();rig=None;reports=[]
    try:
        c.autoKeyframe(state=False)
        prefix='_rotationOwnership_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,False)
        rig=build({k:p for k,p in parts.items() if k.startswith('arm')},namespace=prefix)
        for key,p in rig['parts'].items():
            data=live_alignment.enable(p,'arm');ctrl=data['controls']['middle_fk']
            c.move(-.6 if p['side']=='L' else .6,.5,1,data['controls']['end_fk'],r=True,ws=True)
            companion=[n+'.'+a for n in data['controls'].values() if n!=ctrl for a in live_edit.TR]
            saved=live_edit._snapshot(companion)
            # Only RZ initially has animation: newly needed local calibration
            # must be seeded without changing old keys or leaving constants.
            for t in (6,8,10,12):c.setKeyframe(ctrl,at='rotateZ',time=t)
            c.select(ctrl);c.setToolTo('RotateSuperContext');c.currentTime(6)
            elbow=c.xform(p['joints'][1],q=True,ws=True,t=True)
            c.autoKeyframe(state=True)
            for t,angle in ((6,12),(8,-18),(10,29),(12,-7),(8,11),(10,-14)):
                c.currentTime(t)
                live_edit.before_drag('test');c.rotate(0,0,angle,ctrl,r=True,os=True);live_edit.after_drag('test')
                assert not c.ls(p['namespace']+':rotation_*')
            assert saved==live_edit._snapshot(companion),'Companion changed'
            error=0
            for i in range(49):
                c.currentTime(6+i/8)
                error=max(error,math.dist(elbow,c.xform(p['joints'][1],q=True,ws=True,t=True)))
            assert error<1e-5,('multi-key elbow drift',key,error)
            # Retiming/deleting all ordinary and calibration channels together
            # must be sufficient: there is no historical second animation source.
            c.keyframe(ctrl,e=True,time=(10,10),timeChange=11)
            owned_curves=set(c.ls(type='animCurve'))-set(n for n in before if c.objExists(n) and c.nodeType(n).startswith('animCurve'))
            controls=set(data['controls'].values())|set(p['controls'].values())
            for curve in owned_curves:
                for dest in c.listConnections(curve+'.output',s=False,d=True,p=True) or []:
                    if dest.startswith(p['namespace']+':'):
                        assert dest.split('.')[0] in controls,(curve,dest)
            c.autoKeyframe(state=False);c.currentTime(8)
            c.cutKey(list(controls),clear=True)
            baseline={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
            residual=0
            for t in (0,6,6.25,7.5,8,9.5,11,12,20):
                c.currentTime(t)
                residual=max(residual,max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
            assert residual<1e-5,('Residual motion after deleting controls keys',residual)
            # Surface removal transfers the pivot curves and connections too.
            live_alignment.remove(p['root'])
            reports.append(dict(part=key,multi_key_elbow_error=error,after_delete_motion=residual,hidden_rotation_nodes=0))
        return reports
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(selection,r=True) if selection else c.select(cl=True)
