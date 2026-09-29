"""Matched wrist/foot switches must key only the current frame."""
import maya.cmds as c
from scripts import test_arm_world_ik as arms,test_foot_space as feet
from maya_agent.rigs import arm_ik,foot_space


def verify(kind='arm',layer=None,weight=1.0):
    fixture=arms if kind=='arm' else feet
    try:
        fixture.setup(animated=True)
        parts=fixture.state['arms' if kind=='arm' else 'legs']
        switch=arm_ik.switch if kind=='arm' else foot_space.switch
        pose=(lambda key,p:arms.pose(key)) if kind=='arm' else (lambda key,p:feet.pose(p))
        if layer:
            for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
            edit=c.animLayer('_currentFrameModeLayer',override=layer=='override')
            c.animLayer(edit,e=True,selected=True,preferred=True,weight=weight)
        before={n:set(c.keyframe(n,q=True,tc=True) or []) for n in c.ls(type='animCurve')}
        reports=[]
        for k,p in parts.items():
            for frame,mode in ((10,1),(20,0)):
                c.currentTime(frame);baseline=pose(k,p)
                switch(p['root'],mode,key=True)
                err=fixture.error(baseline,pose(k,p));assert err<1e-5,(k,frame,err)
                c.currentTime(frame+1);c.currentTime(frame)
                replay=fixture.error(baseline,pose(k,p));assert replay<1e-5,(k,frame,replay)
                reports.append(dict(part=k,frame=frame,error=err,replay=replay))
        added=sorted({t for n in c.ls(type='animCurve') for t in set(c.keyframe(n,q=True,tc=True) or [])-before.get(n,set())})
        assert added==[10.0,20.0],added
        return dict(kind=kind,layer=layer,weight=weight,added_times=added,reports=reports)
    finally:
        if fixture.state:fixture.cleanup()
