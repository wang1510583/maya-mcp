"""Verify animation guard failures preserve source curves and targets."""
import maya.cmds as c
from maya_agent.rigs.soft_limb import build_from_selection


def verify():
    before=set(c.ls(long=True))
    selected=c.ls(sl=True,long=True) or []
    frame=c.currentTime(q=True)
    old_auto=c.autoKeyframe(q=True,state=True)
    c.autoKeyframe(state=False)
    root=c.createNode('transform',name='_armAnimationGuards')
    nodes=[c.createNode('transform',name='_armAnimationGuard'+str(i),parent=root) for i in range(3)]
    for i,n in enumerate(nodes):c.setAttr(n+'.translate',i*5,2 if i==1 else 0,0)
    c.setKeyframe(nodes[0],at='rotateY',t=frame,v=0)
    cases=[]
    def rejected(label, **kwargs):
        snapshot=set(c.ls(long=True))
        edges={n+'.'+a:c.connectionInfo(n+'.'+a,sourceFromDestination=True)
               for n in nodes for a in ['translateX','translateY','translateZ','rotateX','rotateY','rotateZ','scaleX']}
        curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        options=dict(targets=nodes,namespace='_armGuardRejected',copy_animation=True,start_frame=frame,end_frame=frame+2)
        options.update(kwargs)
        try:build_from_selection(**options)
        except (ValueError,RuntimeError):pass
        else:raise AssertionError(label+' should fail')
        assert set(c.ls(long=True))==snapshot,label
        assert all(c.connectionInfo(p,sourceFromDestination=True)==src for p,src in edges.items()),label
        assert all((c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==keys for n,keys in curves.items()),label
        assert c.currentTime(q=True)==frame
        cases.append(label)
    try:
        rejected('animation disabled',copy_animation=False)
        rejected('drive disabled',drive_targets=False)
        rejected('invalid sampling',sample_step=0)
        c.setAttr(nodes[1]+'.rotateX',lock=True)
        rejected('locked channel')
        c.setAttr(nodes[1]+'.rotateX',lock=False)
        c.setKeyframe(nodes[1],at='scaleX',t=frame,v=1)
        c.setKeyframe(nodes[1],at='scaleX',t=frame+2,v=2)
        rejected('nonuniform scale at later frame')
        c.delete(c.listConnections(nodes[1]+'.scaleX',s=True,d=False))
        layer=c.animLayer('_armGuardLayer')
        c.animLayer(layer,edit=True,attribute=nodes[2]+'.rotateY')
        c.setKeyframe(nodes[2],at='rotateY',t=frame,v=15,animLayer=layer)
        rejected('animation layer')
        return dict(passed=True,cases=cases)
    finally:
        for n in reversed(c.ls(long=True)):
            if n not in before and c.objExists(n):c.delete(n)
        c.currentTime(frame)
        c.autoKeyframe(state=old_auto)
        c.select(selected,r=True) if selected else c.select(clear=True)
        assert set(c.ls(long=True))==before
