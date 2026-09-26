"""Verify independent L/R parts, copied animation, and explicit general roots."""
import runpy
import uuid
from pathlib import Path
import maya.cmds as c


def verify(animated=True, general=False):
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));frame=c.currentTime(q=True)
    selection=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    c.autoKeyframe(state=False);rig=None
    prefix='_independent_'+uuid.uuid4().hex[:7]
    try:
        fixture,parts=suite['fixture'](prefix,animated,shoulders=True)
        # Old saved True switches must not reintroduce whole-part parenting.
        for options in parts.values():options['connected']=True
        c.currentTime(1)
        rig=build(parts,namespace=prefix,general_root=fixture if general else None)
        assert rig['max_world_error']<1e-4
        assert rig['reference_body'] is None
        assert not any(p['connected'] for p in rig['parts'].values())
        roots={k:c.ls(p['root'],long=True)[0] for k,p in rig['parts'].items()}
        for key,path in roots.items():
            assert not any(path.startswith(other+'|') for k,other in roots.items() if k!=key)
        c.currentTime(3 if animated else 1)
        watched=[n for k,p in parts.items() if k!='body' for n in p['targets']]
        watched += [n for k,p in rig['parts'].items() if k!='body' for n in p['controls'].values() if isinstance(n,str) and c.objExists(n)]
        poses={n:c.xform(n,q=True,ws=True,m=True) for n in watched}
        def add(node,attr,value):
            v=c.getAttr(node+'.'+attr)+value
            if c.listConnections(node+'.'+attr,s=True,d=False):c.setKeyframe(node,at=attr,t=c.currentTime(q=True),v=v)
            else:c.setAttr(node+'.'+attr,v)
            c.dgdirty(node)
        for ctrl in rig['parts']['body']['controls']['hips'],rig['parts']['body']['controls']['chest']:
            add(ctrl,'translateX',2);add(ctrl,'rotateY',13)
        error=max(abs(a-b) for n,m in poses.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        assert error<1e-4,error
        # Shoulder edits cannot drag the arm IK either.
        for side in ('L','R'):
            add(rig['parts']['shoulder_'+side]['controls']['clavicle'],'translateX',1)
        for k in ('arm_L','arm_R'):
            for n in parts[k]['targets']:
                assert max(abs(a-b) for a,b in zip(poses[n],c.xform(n,q=True,ws=True,m=True)))<1e-4
        if general:
            old={k:c.xform(p['targets'][-1],q=True,ws=True,t=True) for k,p in parts.items()}
            add(fixture,'translateX',3)
            for k,p in parts.items():
                new=c.xform(p['targets'][-1],q=True,ws=True,t=True)
                assert max(abs(new[i]-old[k][i]-(3 if i==0 else 0)) for i in range(3))<1e-4,(k,old[k],new)
        return dict(passed=True,animated=animated,general_root=general,parts=len(parts),
                    copy_error=rig['max_world_error'],body_edit_other_parts_error=error)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
