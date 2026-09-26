"""Root joint drives body and connected parts exactly once, including copied motion."""
import runpy
import uuid
import maya.cmds as c
import maya.api.OpenMaya as om


def verify(animated=False):
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path('D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/test_integrated_rig_live.py')
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    prefix='_bodyRoot_'+uuid.uuid4().hex[:7]
    try:
        _,parts=suite['fixture'](prefix,animated,shoulders=True)
        root=c.createNode('joint',name=prefix+'_rootJoint')
        c.setAttr(root+'.translate',4,2,-3);c.setAttr(root+'.rotateY',20)
        if animated:
            for f,t,r in [(1,4,20),(3,6,27),(5,3,12)]:
                c.setKeyframe(root,at='translateX',t=f,v=t);c.setKeyframe(root,at='rotateY',t=f,v=r)
        c.currentTime(1)
        rig=build(parts,namespace=prefix,general_root=root)
        assert rig['parts']['body']['connected']
        assert rig['parts']['body']['attachment']['parent']==c.ls(root,long=True)[0]
        c.currentTime(3 if animated else 1)
        poses={k:[c.xform(n,q=True,ws=True,m=True) for n in p['targets']] for k,p in parts.items()}
        old=om.MMatrix(c.xform(root,q=True,ws=True,m=True))
        for attr,delta in [('translateX',2),('rotateY',17)]:
            value=c.getAttr(root+'.'+attr)+delta
            if animated:c.setKeyframe(root,at=attr,t=c.currentTime(q=True),v=value);c.dgdirty(root)
            else:c.setAttr(root+'.'+attr,value)
        change=old.inverse()*om.MMatrix(c.xform(root,q=True,ws=True,m=True))
        error=0
        for key,p in parts.items():
            for n,m in zip(p['targets'],poses[key]):
                expected=om.MMatrix(m) if key=='leg_L' else om.MMatrix(m)*change
                delta=max(abs(a-b) for a,b in zip(list(expected),c.xform(n,q=True,ws=True,m=True)))
                error=max(error,delta);assert delta<1e-4,(key,n,delta)
        return dict(passed=True,animated=animated,joint_root=True,body_and_children_follow_once=True,
                    disconnected_independent=True,motion_error=rig['max_world_error'],follow_error=error)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
