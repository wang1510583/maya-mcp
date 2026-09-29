"""Upper-arm matching on disposable rigs, including current-frame-only keys."""
import maya.cmds as c
from scripts import test_arm_world_ik as arms
from maya_agent.rigs import upper_arm_space,arm_ik,live_edit

state=None


def setup(animated=True,live=True):
    global state
    arms.setup(animated,callbacks=True,live=live);state=arms.state
    for p in state['arms'].values():
        space=next(s for s in state['rig']['spaces'] if s['control']==p['controls']['shoulder_fk'])
        upper_arm_space.enable(p,space)


def cleanup():
    global state
    arms.cleanup();state=None


def verify(live=True,ik=False,layer=None,weight=1.0):
    try:
        setup(live=live);reports=[]
        if layer:
            for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
            l=c.animLayer('_upperArmSpaceLayer',override=layer=='override')
            c.animLayer(l,e=True,selected=True,preferred=True,weight=weight)
        original={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        for k,p in state['arms'].items():
            source=p['controls']['shoulder_fk'];chest=state['rig']['parts']['body']['controls']['chest']
            c.currentTime(10)
            if ik:arm_ik.switch(p['root'],1,key=False)
            c.move(.3,-.2,.1,chest,r=True,ws=True);c.rotate(12,-9,7,chest,r=True,os=True)
            before=arms.pose(k);a=upper_arm_space.switch(source,1,key=bool(layer));delta=arms.error(before,arms.pose(k))
            assert delta<1e-5,(k,delta)
            if layer:
                keys=c.animLayer(l,q=True,animCurves=True) or []
                assert all(set(c.keyframe(n,q=True,tc=True) or []).issubset({10.0}) for n in keys),'Extra frame keyed'
            before=arms.pose(k);b=upper_arm_space.switch(source,0,key=False)
            assert arms.error(before,arms.pose(k))<1e-5
            reports.append(dict(part=k,enter=a,return_switch=b))
        if layer:
            assert original=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in original},'Base curves changed'
        return dict(live=live,ik=ik,layer=layer,weight=weight,reports=reports)
    finally:
        if state:cleanup()
