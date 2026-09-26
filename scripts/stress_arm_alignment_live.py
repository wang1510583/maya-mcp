"""Recalculation pose sweep on isolated rigs, with original scene restoration."""
import uuid,math,random
import maya.cmds as c
import maya.mel as mel


def run(count=30):
    from maya_agent.rigs.soft_limb import build_from_selection
    from maya_agent.rigs.soft_leg import cleanup
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);ns='_alignmentStress_'+uuid.uuid4().hex[:7]
    report=[]
    try:
        targets=[]
        for i,p in enumerate([(5,18,2),(10,14,4),(13,9,-1)]):
            n=c.createNode('transform',name=ns+'_target'+str(i));c.xform(n,ws=True,t=p);targets.append(n)
        rig=build_from_selection(targets,namespace=ns)
        controls=[rig['controls'][k] for k in ('shoulder_fk','middle_fk','end_fk','end_locator','pole_locator')]
        attrs={n+'.'+a:c.getAttr(n+'.'+a) for n in controls for a in ('translateX','translateY','translateZ','rotateX','rotateY','rotateZ') if not c.getAttr(n+'.'+a,lock=True)}
        randomizer=random.Random(260927)
        for i in range(count):
            for n in c.ls(ns+':*',type='animCurve') or []:c.delete(n)
            for plug,value in attrs.items():c.setAttr(plug,value)
            fk=rig['controls']['middle_fk'];pose={}
            for a in ('translateX','translateY','translateZ','rotateX','rotateY','rotateZ'):
                delta=randomizer.uniform(-5,5) if a.startswith('translate') else randomizer.uniform(-175,175)
                pose[a]=attrs[fk+'.'+a]+delta;c.setAttr(fk+'.'+a,pose[a])
            pre=[c.xform(n,q=True,ws=True,m=True) for n in rig['joints']]
            references=[c.xform(ns+':base_L'+str(i),q=True,ws=True,m=True) for i in (1,2,3)]
            c.select(fk,r=True)
            try:mel.eval('kurok_recalculate_system(0);');error=None
            except Exception as exc:error=str(exc)
            drift=max(abs(a-b) for n,m in zip(rig['joints'],pre) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
            alignment=max(abs(a-b) for n,m in zip(controls[:3],references) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
            report.append(dict(pose=pose,drift=drift,alignment=alignment,error=error))
        return sorted(report,key=lambda x:x['drift'],reverse=True)
    finally:
        for n in c.ls(ns+':*',type='constraint') or []:
            if c.objExists(n):c.delete(n)
        if c.namespace(exists=ns):cleanup(ns)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
