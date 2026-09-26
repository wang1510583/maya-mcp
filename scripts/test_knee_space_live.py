"""Knee spaces: same-side foot translation/rotation, L/R and copied animation."""
import runpy,uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om


def verify(animated=False,foot_space=False):
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    prefix='_kneeSpace_'+uuid.uuid4().hex[:7]
    try:
        _,parts=suite['fixture'](prefix,animated)
        legs={k:dict(v,space_knee=True,space_foot=foot_space) for k,v in parts.items() if k.startswith('leg')}
        c.currentTime(1);rig=build(legs,namespace=prefix)
        assert rig['max_world_error']<1e-4
        c.currentTime(3 if animated else 1);error=0.0
        def pose(n):return om.MMatrix(c.xform(n,q=True,ws=True,m=True))
        def write(n,attr,value):
            if c.listConnections(n+'.'+attr,s=True,d=False):c.setKeyframe(n,at=attr,t=c.currentTime(q=True),v=value)
            else:c.setAttr(n+'.'+attr,value)
            c.dgdirty(n)
        for side in ('L','R'):
            p=rig['parts']['leg_'+side];knee=p['controls']['knee'];foot=p['controls']['foot']
            other=rig['parts']['leg_'+('R' if side=='L' else 'L')]['controls']['knee']
            assert c.getAttr(knee+'.spaceDriver')==foot
            assert c.attributeQuery('global',node=knee,niceName=True)=='global'
            assert c.getAttr(knee+'.global')==0
            values={a:c.getAttr(foot+'.'+a) for a in ('translateX','rotateY')}
            old_knee=pose(knee);local_knee=old_knee;old_foot=pose(foot);old_other=pose(other)
            write(foot,'translateX',values['translateX']+2)
            assert max(abs(a-b) for a,b in zip(old_knee,pose(knee)))<1e-4
            write(foot,'translateX',values['translateX'])
            c.setAttr(knee+'.global',1)
            # Animated spaces can already differ from the construction frame.
            # The existing switch intentionally does not perform pose matching.
            old_knee=pose(knee)
            write(foot,'translateX',values['translateX']+2);write(foot,'rotateY',values['rotateY']+25)
            expected=old_knee*old_foot.inverse()*pose(foot)
            error=max(error,max(abs(a-b) for a,b in zip(expected,pose(knee))))
            assert error<1e-4,error
            assert max(abs(a-b) for a,b in zip(old_other,pose(other)))<1e-4
            c.setAttr(knee+'.global',0)
            assert max(abs(a-b) for a,b in zip(local_knee,pose(knee)))<1e-4
            for a,v in values.items():write(foot,a,v)
        return dict(passed=True,animated=animated,foot_space=foot_space,copy_error=rig['max_world_error'],follow_error=error)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
