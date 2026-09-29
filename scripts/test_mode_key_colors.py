"""Maya regression: native foot ticks and automatic discovery of new rigs.

Call setup(), allow Maya idle callbacks, check(), then cleanup().
"""
import maya.cmds as c
from scripts import test_foot_space as feet
from maya_agent.rigs import foot_space,wrist_key_colors,arm_ik


def setup():
    feet.setup(animated=True)
    for p in feet.state['legs'].values():c.setKeyframe(p['controls']['foot']+'.global',t=5,v=0,ott='step')
    before={n:set(c.keyframe(n,q=True,tc=True) or []) for n in c.ls(type='animCurve')}
    for p in feet.state['legs'].values():
        assert p['root'] in wrist_key_colors._roots,'New foot not registered'
        c.currentTime(10);foot_space.switch(p['root'],1,key=True)
        c.currentTime(15);foot_space.switch(p['root'],0,key=True)
    added={t for n in c.ls(type='animCurve') for t in set(c.keyframe(n,q=True,tc=True) or [])-before.get(n,set())}
    assert added=={10.0,15.0},added
    feet.state['color_curves']={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyframe(n,q=True,breakdown=True)) for p in feet.state['legs'].values() for n in wrist_key_colors._curves(wrist_key_colors._data(p['root']))}


def check():
    reports=[]
    for p in feet.state['legs'].values():
        data=wrist_key_colors._data(p['root']);marked=set();normal=set()
        for n in wrist_key_colors._curves(data):
            for i,t in enumerate(c.keyframe(n,q=True,tc=True) or []):
                flag=bool(c.getAttr(n+'.keyTickDrawSpecial[%d]'%i))
                assert flag==bool(10<=t<15),(n,t,flag)
                (marked if flag else normal).add(t)
        reports.append(dict(control=data['control'],green=sorted(marked),normal=sorted(normal)))
    assert feet.state['color_curves']=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyframe(n,q=True,breakdown=True)) for n in feet.state['color_curves']}
    return reports


def cleanup():
    feet.cleanup()
