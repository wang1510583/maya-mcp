"""A moved pose and a subsequent elbow bend must use the same FK encoding."""
import uuid,math
import maya.cmds as c
from maya_agent.rigs import live_alignment,live_edit
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove


def verify():
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();rig=None;reports=[]
    try:
        c.autoKeyframe(state=False);prefix='_armPoseEncoding_'+uuid.uuid4().hex[:6]
        _,parts=fixture(prefix,False)
        rig=build({k:v for k,v in parts.items() if k.startswith('arm')},namespace=prefix)
        for key,p in rig['parts'].items():
            d=live_alignment.enable(p,'arm');ctrl=d['controls'];ns=p['namespace'];side=p['side']
            nodes=list(ctrl.values())+[ns+':elb_'+side+'1',ns+':hand_'+side+'1']
            for n in nodes:c.setKeyframe(n,at=list(live_edit.TR),time=0)
            c.currentTime(16);c.autoKeyframe(state=True)
            c.select(ctrl['middle_fk']);c.setToolTo('moveSuperContext')
            live_edit.before_drag('test');c.move(-.4,.3,.2,ctrl['middle_fk'],r=True,ws=True)
            live_edit.update_drag();before_release={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
            live_edit.after_drag('test')
            release=max(abs(a-b) for n,m in before_release.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
            assert release<1e-5,release
            shoulder=live_edit._snapshot([ctrl['shoulder_fk']+'.'+a for a in live_edit.TR])[1]
            fixed=c.xform(p['joints'][0],q=True,ws=True,m=True);elbow=c.xform(p['joints'][1],q=True,ws=True,t=True)
            for t,angle in ((21,-35),(21,12)):
                c.currentTime(t);c.select(ctrl['middle_fk']);c.setToolTo('RotateSuperContext')
                live_edit.before_drag('test');c.rotate(0,0,angle,ctrl['middle_fk'],r=True,os=True);live_edit.after_drag('test')
                updated=live_edit._snapshot([ctrl['shoulder_fk']+'.'+a for a in live_edit.TR])[1]
                assert updated==shoulder,('Elbow bend changed shoulder curves',shoulder,updated)
            drift=0
            for i in range(21):
                c.currentTime(16+i*.25)
                drift=max(drift,max(abs(a-b) for a,b in zip(fixed,c.xform(p['joints'][0],q=True,ws=True,m=True))),
                          math.dist(elbow,c.xform(p['joints'][1],q=True,ws=True,t=True)))
            assert drift<1e-5,(side,drift)
            # Deleting every animator control's keys must leave no hidden motion.
            c.autoKeyframe(state=False);c.cutKey(nodes,clear=True)
            pose={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']};residual=0
            for t in (0,16,18.5,21,25):
                c.currentTime(t)
                residual=max(residual,max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
            assert residual<1e-5,residual
            reports.append(dict(side=side,held_shoulder_error=drift,release_error=release,residual_motion=residual,shoulder_curves_unchanged=True))
        return reports
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.setToolTo(tool);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(cl=True)
