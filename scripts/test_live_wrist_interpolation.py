"""Wrist-only keys must not reparameterize the arm or disturb subframe holds."""
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_alignment,live_edit


def verify(global_space=False):
    before=set(c.ls(long=True));time=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();rig=None;reports=[]
    try:
        c.autoKeyframe(state=False)
        prefix='_wristHold_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,True)
        for p in parts.values():p.update(space_upper_arm=True,space_wrist=True)
        c.currentTime(5)
        rig=build({k:p for k,p in parts.items() if k.startswith('arm')},namespace=prefix)
        for key,p in rig['parts'].items():
            d=live_alignment.enable(p,'arm');ns=p['namespace'];side=p['side']
            wrist=d['controls']['end_fk'];pole=ns+':elb_'+side+'1'
            # Deliberately leave the input FK basis different from solved bones.
            c.move(-.45,.3,.2,d['controls']['middle_fk'],r=True,ws=True)
            c.setAttr(wrist+'.global',int(global_space))
            nodes=list(d['controls'].values())+[pole]
            for node in nodes:
                for attr in live_edit.TR:
                    plug=node+'.'+attr
                    if c.getAttr(plug,lock=True):continue
                    value=c.getAttr(plug)
                    for frame in (6,12):c.setKeyframe(plug,time=frame,value=value)
            companions=[n for n in nodes if n!=wrist]
            channels=[n+'.'+a for n in companions for a in live_edit.TR]
            original=live_edit._snapshot(channels)[1]
            baseline={}
            for frame in [6+i*.25 for i in range(25)]:
                c.currentTime(frame)
                baseline[frame]={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']+[pole]}
            c.setToolTo('RotateSuperContext');c.select(wrist)
            c.autoKeyframe(state=True)
            for frame,rotation in ((6,(0,0,18)),(12,(-24,0,0))):
                c.currentTime(frame)
                assert live_edit._wrist_rotation(p['root'])
                live_edit.before_drag('test')
                # v1.9 snapshots the chain for undo, but must only change the
                # wrist. Ownership is checked by the actual curve audit below.
                c.rotate(*rotation,wrist,r=True,os=True)
                live_edit.after_drag('test')
            assert original==live_edit._snapshot(channels)[1],'Companion keys or tangents changed'
            error=0
            for frame,pose in baseline.items():
                c.currentTime(frame)
                for node,matrix in pose.items():
                    actual=c.xform(node,q=True,ws=True,m=True)
                    indices=range(12,15) if node==p['joints'][2] else range(16)
                    error=max(error,max(abs(matrix[i]-actual[i]) for i in indices))
            assert error<1e-5,(key,error)
            reports.append(dict(part=key,global_space=global_space,subframes=25,hold_error=error,companion_curves_unchanged=True))
            c.autoKeyframe(state=False)
        return reports
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for node in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(node):c.delete(node)
        c.currentTime(time);c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(selection,r=True) if selection else c.select(cl=True)
