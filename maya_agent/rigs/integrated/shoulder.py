"""Single clavicle FK control, fitted to captured input without touching sources."""
import math


def build(item,targets,namespace,side):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    c.namespace(add=namespace)
    root=c.createNode('transform',name=namespace+':rig_root')
    zero=c.createNode('transform',name=namespace+':clavicle_zero',parent=root)
    current=c.currentTime(q=True);pose=item['motion'][current][0]
    matrix=list(pose['rotation']);matrix[12:15]=pose['pivot']
    c.xform(zero,ws=True,m=matrix)
    size=float(item['options'].get('control_size',1.0))
    if not math.isfinite(size) or size<=0:raise ValueError('肩膀控制器大小必须大于零。')
    points=[(-1,1,1),(1,1,1),(1,1,-1),(-1,1,-1),(-1,1,1),(-1,-1,1),
            (-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1),(1,-1,1),(1,1,1),
            (1,1,-1),(1,-1,-1),(-1,-1,-1),(-1,1,-1)]
    ctrl=c.curve(name=namespace+':Clavicle_'+side,d=1,p=[tuple(size*v for v in p) for p in points])
    c.parent(ctrl,zero,relative=True)
    c.setAttr(ctrl+'.overrideEnabled',True);c.setAttr(ctrl+'.overrideColor',13 if side=='R' else 6)
    inverse=om.MMatrix(matrix).inverse();previous=None
    if item['frames']:
        for frame,poses in sorted(item['motion'].items()):
            m=list(poses[0]['rotation']);m[12:15]=poses[0]['pivot']
            tm=om.MTransformationMatrix(om.MMatrix(m)*inverse)
            r=tm.rotation(asQuaternion=True).asEulerRotation()
            if previous is not None:r=r.closestSolution(previous)
            previous=r;t=tm.translation(om.MSpace.kTransform)
            for a,v in zip(('translateX','translateY','translateZ','rotateX','rotateY','rotateZ'),list(t)+[math.degrees(v) for v in r]):
                c.setKeyframe(ctrl,at=a,t=frame,v=v,itt='linear',ott='linear')
        c.dgdirty(ctrl)
    for attr in ('translate','rotate'):
        for axis in 'XYZ':
            plug=targets[0]+'.'+attr+axis
            source=c.connectionInfo(plug,sourceFromDestination=True)
            if source:c.disconnectAttr(source,plug)
    constraint=c.parentConstraint(ctrl,targets[0],mo=False,name=namespace+':outputConstraint')[0]
    return dict(namespace=namespace,root=root,controls={'clavicle':ctrl},side=side,
                nodes=[root,zero,ctrl,constraint],target_mapping=[dict(target=targets[0],control=ctrl)])
