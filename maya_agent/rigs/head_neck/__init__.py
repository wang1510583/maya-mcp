"""Reference-style head and neck: independent head, blended neck orientation."""
import math

VERSION='1.1.0'
CHANNELS=tuple(p+a for p in ('translate','rotate') for a in 'XYZ')


def build(item,targets,namespace,chest=None):
    """Internal integrated constructor; source motion is captured before entry."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    c.namespace(add=namespace)
    root=c.createNode('transform',name=namespace+':rig_root')
    # The reference's controls share an upright character frame, rather than
    # inheriting differently oriented bone axes. Bind offsets drive the bones.
    if c.upAxis(q=True,axis=True)=='y':c.setAttr(root+'.rotateX',-90)
    control_frame=c.xform(root,q=True,ws=True,m=True)
    frame=c.currentTime(q=True);poses=item['motion'][frame]
    count=len(poses)
    if not 2<=count<=64:raise ValueError('头颈需要至少一根颈骨和一个头部目标。')
    def matrix(pose):
        m=list(pose['rotation']);m[12:15]=pose['pivot'];return m
    if not chest:
        chest=c.createNode('transform',name=namespace+':chest_reference',parent=root)
        m=list(control_frame);m[12:15]=poses[0]['pivot'];c.xform(chest,ws=True,m=m)
    chest_frame=c.createNode('transform',name=namespace+':chest_orientation',parent=chest)
    m=list(control_frame);m[12:15]=c.xform(chest,q=True,ws=True,t=True)
    c.xform(chest_frame,ws=True,m=m)
    size=float(item['options'].get('control_size',1.0))
    if not math.isfinite(size) or size<=0:raise ValueError('控制器大小必须大于零。')
    distance=math.dist(poses[0]['pivot'],poses[-1]['pivot'])
    radius=max(distance*.5,.1)*size
    head=c.spaceLocator(name=namespace+':Head_ctr1')[0]
    c.parent(head,root,relative=True)
    c.xform(head,ws=True,t=poses[-1]['pivot'])
    shape=c.listRelatives(head,s=True)[0]
    c.setAttr(shape+'.localScale',radius*2,radius*2,0,type='double3')
    controls=[];groups=[];blends=[];previous=chest
    for i,pose in enumerate(poses[:-1]):
        zero=c.createNode('transform',name=namespace+':neck{:02d}_blend'.format(i+1),parent=root)
        c.xform(zero,ws=True,t=pose['pivot'])
        anchor=c.createNode('transform',name=namespace+':neck{:02d}_anchor'.format(i+1),parent=previous)
        c.xform(anchor,ws=True,t=pose['pivot'])
        c.setAttr(anchor+'.visibility',False)
        c.pointConstraint(anchor,zero,mo=False,name=namespace+':neck{:02d}_position'.format(i+1))
        orient=c.orientConstraint(chest_frame,head,zero,mo=False,name=namespace+':neck{:02d}_orientation'.format(i+1))[0]
        weights=c.orientConstraint(orient,q=True,weightAliasList=True)
        fraction=(i+1)/float(count)
        c.setAttr(orient+'.'+weights[0],1-fraction);c.setAttr(orient+'.'+weights[1],fraction)
        c.setAttr(orient+'.interpType',2)
        ctrl=c.createNode('joint',name=namespace+':neck_ctr'+str(i+1),parent=zero)
        c.setAttr(ctrl+'.radius',radius)
        c.setAttr(ctrl+'.overrideEnabled',True);c.setAttr(ctrl+'.overrideColor',17)
        controls.append(ctrl);groups.append(zero);blends.append(orient);previous=ctrl
    # Position drives the head's own translation, never its parent matrix.
    # Neck orientation reads head.rotate + parentMatrix, so this keeps the
    # point-follow and rotation-blend graphs acyclic, as in the reference file.
    head_anchor=c.createNode('transform',name=namespace+':head_anchor',parent=previous)
    c.xform(head_anchor,ws=True,t=poses[-1]['pivot'])
    c.setAttr(head_anchor+'.visibility',False)
    position=c.pointConstraint(head_anchor,head,mo=False,name=namespace+':head_positionConstraint')[0]
    c.addAttr(head,ln='positionOffset',at='double3')
    for axis in 'XYZ':c.addAttr(head,ln='positionOffset'+axis,at='double',parent='positionOffset',keyable=True)
    total=c.createNode('plusMinusAverage',name=namespace+':head_positionOffset')
    for axis in 'XYZ':c.disconnectAttr(position+'.constraintTranslate'+axis,head+'.translate'+axis)
    c.connectAttr(position+'.constraintTranslate',total+'.input3D[0]')
    c.connectAttr(head+'.positionOffset',total+'.input3D[1]')
    c.connectAttr(total+'.output3D',head+'.translate')
    for axis in 'XYZ':c.setAttr(head+'.translate'+axis,keyable=False,channelBox=False)
    controls.append(head)
    drivers=[];bind_offsets={}
    for i,(ctrl,pose) in enumerate(zip(controls,poses)):
        driver=c.createNode('transform',name=namespace+':output_frame'+str(i+1),parent=ctrl)
        c.xform(driver,ws=True,m=matrix(pose));drivers.append(driver)
        bind_offsets[ctrl]=om.MMatrix(c.getAttr(driver+'.matrix'))
    # Solve head rotation first: every neck blend reads it. Then solve necks
    # root-to-tip and finally head translation, without reading driven targets.
    previous_eulers={}
    def values(node,pose):
        parent=c.listRelatives(node,p=True,fullPath=True)[0]
        desired=bind_offsets[node].inverse()*om.MMatrix(matrix(pose))
        tm=om.MTransformationMatrix(desired*om.MMatrix(c.xform(parent,q=True,ws=True,m=True)).inverse())
        e=tm.rotation(asQuaternion=True).asEulerRotation()
        if node in previous_eulers:e=e.closestSolution(previous_eulers[node])
        previous_eulers[node]=e
        return list(tm.translation(om.MSpace.kTransform))+[math.degrees(v) for v in e]
    def write(node,attrs,values,f):
        for a,v in zip(attrs,values):
            if item['frames']:c.setKeyframe(node,at=a,t=f,v=v,itt='linear',ott='linear')
            else:c.setAttr(node+'.'+a,v)
        c.dgdirty(node)
    try:
        for f,desired in sorted(item['motion'].items()):
            c.currentTime(f)
            write(head,CHANNELS[3:],values(head,desired[-1])[3:],f)
            for ctrl,pose in zip(controls[:-1],desired[:-1]):
                write(ctrl,CHANNELS,values(ctrl,pose),f)
            translation=values(head,desired[-1])[:3]
            base=c.getAttr(position+'.constraintTranslate')[0]
            write(head,['positionOffset'+a for a in 'XYZ'],[a-b for a,b in zip(translation,base)],f)
    finally:c.currentTime(frame)
    mappings=[]
    for ctrl,driver,target in zip(controls,drivers,targets):
        for a in CHANNELS:
            source=c.connectionInfo(target+'.'+a,sfd=True)
            if source:c.disconnectAttr(source,target+'.'+a)
        constraint=c.parentConstraint(driver,target,mo=False,name=namespace+':outputConstraint')[0]
        mappings.append(dict(target=target,control=ctrl,driver=driver,constraint=constraint))
    return dict(namespace=namespace,root=root,version=VERSION,
                controls=dict({'head':head},**{'neck'+str(i+1):n for i,n in enumerate(controls[:-1])}),
                target_mapping=mappings,neck_groups=groups,neck_blends=blends,
                head_position=position,chest_driver=chest,chest_orientation=chest_frame,
                output_frames=drivers,head_anchor=head_anchor)
