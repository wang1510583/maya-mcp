"""Spine controls and outputs must share the hips' rigid world delta."""
import maya.cmds as c
import maya.api.OpenMaya as om
from scripts import test_body_direction as fixture
from maya_agent.rigs import body_follow,body_direction,zero_channels,chest_space


def verify(count=4,animated=False,general=False):
    try:
        p=fixture.setup(count=count,animated=animated,general=general)
        h=p['controls']['hips'];ch=p['controls']['chest']
        # Compare the old path with global=0 at integer and in-between frames.
        zero_channels.build(fixture.state['assembly'])
        hip=p['zero_controls']['hips'];chest=p['zero_controls']['chest']
        chest_space.switch(ch,1,key=False)
        for attr,amount in [('tx',2),('ty',3),('tz',-1),('rx',10),('ry',5),('rz',-10)]:
            c.setAttr(chest+'.'+attr,c.getAttr(chest+'.'+attr)+amount)
        for n in list(p['zero_controls'].values())[1:-1]:
            for a in ('rx','ry','rz','tx'):c.setAttr(n+'.'+a,c.getAttr(n+'.'+a)+.15)
        before=fixture.pose();hm=om.MMatrix(c.xform(h,q=True,ws=True,m=True))
        for a,d in [('rx',20),('ry',35),('rz',-25),('tx',1),('ty',2),('tz',3)]:c.setAttr(hip+'.'+a,c.getAttr(hip+'.'+a)+d)
        delta=hm.inverse()*om.MMatrix(c.xform(h,q=True,ws=True,m=True))
        error=max(abs(a-b) for n,v in before.items() for a,b in zip(om.MMatrix(v)*delta,c.xform(n,q=True,ws=True,m=True)))
        assert error<1e-5,error
        reports=[]
        for mode in (1,0,1,0):reports.append(body_direction.switch(h,mode,key=True))
        c.setKeyframe(list(p['zero_controls'].values()))
        pose=fixture.pose();time=c.currentTime(q=True);c.currentTime(time+.5);c.currentTime(time)
        replay=fixture.error(pose,fixture.pose());assert replay<1e-5,replay
        cycles=[n for n in c.cycleCheck(all=True,list=True) or [] if p['namespace'] in n]
        assert not cycles,cycles
        return dict(count=count,animated=animated,general=general,follow_error=error,replay_error=replay,
                    switch_error=max(r['max_pose_error'] for r in reports))
    finally:fixture.cleanup()
