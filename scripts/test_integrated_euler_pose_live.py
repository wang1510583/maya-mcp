"""Preserve blocking poses when Euler continuity crosses a near-gimbal pose."""
import math
import uuid
import maya.cmds as c
import maya.api.OpenMaya as om


def verify():
    from maya_agent.rigs.integrated import builder
    from maya_agent.rigs.soft_leg import cleanup
    angles=[(.00004000192575277917,89.99994794625398,0),
            (-66.44509558162726,65.71039372050824,-35.040707909947116),
            (146.21980356550696,87.11478340361604,-129.11514980012947)]
    rotations=[om.MEulerRotation(*[math.radians(a) for a in row]) for row in angles]
    def error(a,b):return max(abs(x-y) for x,y in zip(list(a.asMatrix()),list(b.asMatrix())))
    old_error=error(rotations[1],rotations[1].closestSolution(rotations[0]))
    assert old_error>.1,old_error
    previous=None
    for rotation in rotations:
        selected=builder.pose_preserving_euler(rotation,previous)
        assert error(rotation,selected)<1e-10
        previous=selected
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True);ns='_eulerPose_'+uuid.uuid4().hex[:7]
    try:
        c.namespace(add=ns);group=c.createNode('transform',name=ns+':group')
        motion={f:list(r.asMatrix()) for f,r in enumerate(rotations)}
        for f,m in motion.items():m[12:15]=[f,2,3]
        item=dict(frames=[0,1,2],motion={f:[dict(rotation=list(r.asMatrix()),matrix=motion[f],pivot=[f,2,3])] for f,r in enumerate(rotations)})
        c.currentTime(0)
        proxies=builder.proxies(item,ns,group,'leg_L')
        reference=builder.root_reference(ns,group,motion,True)
        maximum=0.
        for f,m in motion.items():
            c.currentTime(f)
            for n in proxies+[reference]:maximum=max(maximum,max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
        assert maximum<1e-10,maximum
        return dict(passed=True,old_rotation_matrix_error=old_error,new_matrix_error=maximum)
    finally:
        cleanup(ns);c.currentTime(time)
        c.select(sel,r=True) if sel else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(long=True))==before
