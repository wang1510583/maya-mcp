"""Partial rigs use external torso anchors without dragging world-space extremities."""
import runpy
import uuid
from pathlib import Path
import maya.cmds as c


def verify(animated=False,general=False,shoulders=True):
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));sel=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    rig=None;prefix='_externalFollow_'+uuid.uuid4().hex[:7]
    def pose(n):return c.xform(n,q=True,ws=True,m=True)
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    def add(n,a,v):
        value=c.getAttr(n+'.'+a)+v
        if c.listConnections(n+'.'+a,s=True,d=False):
            c.setKeyframe(n,at=a,t=c.currentTime(q=True),v=value)
        else:c.setAttr(n+'.'+a,value)
        c.dgdirty(n)
    try:
        root,parts=suite['fixture'](prefix,animated,shoulders=shoulders)
        body=parts.pop('body');chest=body['targets'][-1];hips=body['targets'][0]
        for side in ('L','R'):
            parts['arm_'+side].update(space_upper_arm=True,space_wrist=True)
            parts['leg_'+side].update(space_foot=True,space_knee=True)
        parts['head']['space_head']=True
        c.currentTime(1)
        snapshot=set(c.ls(long=True))
        try:build(parts,namespace=prefix+'_invalid',chest_follow=parts['arm_L']['targets'][0])
        except ValueError:pass
        else:raise AssertionError('Target as anchor must fail before creation')
        assert set(c.ls(long=True))==snapshot
        rig=build(parts,namespace=prefix,general_root=root if general else None,
                  chest_follow=chest,hips_follow=hips)
        assert rig['max_world_error']<1e-4
        c.currentTime(3 if animated else 1)
        arms=[rig['parts']['arm_'+s]['controls']['shoulder_fk'] for s in ('L','R')]
        hands=[rig['parts']['arm_'+s]['controls']['end_fk'] for s in ('L','R')]
        feet=[rig['parts']['leg_'+s]['controls']['foot'] for s in ('L','R')]
        hip_controls=[rig['parts']['leg_'+s]['controls']['hip'] for s in ('L','R')]
        for n in hands:c.setAttr(n+'.global',1)
        original={n:pose(n) for n in arms+hands+feet}
        add(chest,'rotateY',20)
        for n in hands+feet:assert error(original[n],pose(n))<1e-4,(n,'world drift')
        for n in arms:
            assert error(original[n][:12],pose(n)[:12])<1e-4,(n,'local arm rotated')
            assert error(original[n][12:15],pose(n)[12:15])>.01,(n,'arm base did not follow')
        for n in arms:c.setAttr(n+'.global',1)
        original={n:pose(n) for n in arms+hands+feet}
        add(chest,'rotateY',10)
        for n in arms:assert error(original[n][:12],pose(n)[:12])>.01,(n,'global arm did not follow')
        for n in hands+feet:assert error(original[n],pose(n))<1e-4,(n,'world drift with global arm')
        original={n:pose(n) for n in feet+hip_controls}
        add(hips,'rotateZ',15);add(hips,'translateX',2)
        for n in feet:assert error(original[n],pose(n))<1e-4,(n,'foot moved with pelvis')
        for n in hip_controls:assert error(original[n][12:15],pose(n)[12:15])>.01
        for n in feet:c.setAttr(n+'.global',1)
        original={n:pose(n) for n in feet}
        add(hips,'translateX',1)
        for n in feet:assert abs(pose(n)[12]-original[n][12]-1)<1e-4
        if general:
            for n in feet:c.setAttr(n+'.global',0)
            original={n:pose(n) for n in hands+feet+arms+hip_controls}
            add(root,'translateZ',3)
            for n in original:assert abs(pose(n)[14]-original[n][14]-3)<1e-4,(n,'root motion doubled')
        return dict(passed=True,animated=animated,general_root=general,shoulders=shoulders,
                    copy_error=rig['max_world_error'],parts=len(rig['parts']),extremities_stable=True)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
