"""Clavicle locator point link, keeping FK rotations and animation channels editable."""


def point_link(rig,item,assembly_root,control=None,locator=None,label='shoulder'):
    import maya.cmds as c
    from .builder import root_reference
    ns=rig['namespace'];ctrl=control or rig['controls']['shoulder_fk'];locator=locator or rig['shoulder_locator']
    frame=c.currentTime(q=True);motion={};loc_motion={}
    try:
        for f in sorted(set(item['frames'])|{frame}):
            c.currentTime(f)
            motion[f]=c.xform(ctrl,q=True,ws=True,m=True)
            loc_motion[f]=c.xform(locator,q=True,ws=True,m=True)
    finally:c.currentTime(frame)
    base_ctrl=root_reference(ns,assembly_root,motion,bool(item['frames']),'shoulder_fk_reference')
    base_loc=root_reference(ns,assembly_root,loc_motion,bool(item['frames']),'shoulder_locator_reference')
    # Delta-only point motion is added to the original FK base trajectory.
    # Frozen references do not read the live controls, so edits are never canceled.
    positions=[]
    for name,node,with_root in [('liveLocator',locator,False),('baseFK',base_ctrl,True),('baseLocator',base_loc,True)]:
        plug=node+'.worldMatrix[0]'
        if with_root:
            matrix=c.createNode('multMatrix',name=ns+':'+name+'_pointMatrix')
            c.connectAttr(plug,matrix+'.matrixIn[0]');c.connectAttr(rig['root']+'.worldMatrix[0]',matrix+'.matrixIn[1]')
            plug=matrix+'.matrixSum'
        decompose=c.createNode('decomposeMatrix',name=ns+':'+name+'_pointPosition')
        c.connectAttr(plug,decompose+'.inputMatrix');positions.append(decompose+'.outputTranslate')
    delta=c.createNode('plusMinusAverage',name=ns+':shoulder_pointDelta');c.setAttr(delta+'.operation',2)
    c.connectAttr(positions[0],delta+'.input3D[0]');c.connectAttr(positions[2],delta+'.input3D[1]')
    total=c.createNode('plusMinusAverage',name=ns+':shoulder_pointGoal')
    c.connectAttr(delta+'.output3D',total+'.input3D[0]');c.connectAttr(positions[1],total+'.input3D[1]')
    goal=c.createNode('transform',name=ns+':shoulder_pointDriver',parent=assembly_root)
    c.setAttr(goal+'.inheritsTransform',False);c.setAttr(goal+'.visibility',False)
    c.connectAttr(total+'.output3D',goal+'.translate')
    parent=c.listRelatives(ctrl,p=True,fullPath=True)[0]
    group=c.createNode('transform',name=ns+':shoulder_pointOffset',parent=parent)
    c.parent(ctrl,group,relative=True)
    # The group pivot tracks the child's translation, allowing pointConstraint to
    # solve the offset without replacing or locking the child's animation curves.
    c.connectAttr(ctrl+'.translate',group+'.rotatePivot')
    constraint=c.pointConstraint(goal,group,mo=False,name=ns+':shoulder_pointConstraint')[0]
    for axis in 'XYZ':c.setAttr(ctrl+'.translate'+axis,lock=True)
    rig[label+'_point_link']=dict(group=group,driver=goal,constraint=constraint,locator=locator)


def arm_container(group,locator,namespace,parent=None,reference=None):
    """Place arm hierarchically under clavicle but inherit the torso frame once.

    Clavicle itself moves the upper-arm point link, not the whole arm rotation.
    """
    import maya.cmds as c
    matrix=c.createNode('multMatrix',name=namespace+':shoulder_containerSpace')
    if parent:
        if reference:c.connectAttr(reference+'.worldInverseMatrix[0]',matrix+'.matrixIn[0]')
        else:c.setAttr(matrix+'.matrixIn[0]',*c.getAttr(parent+'.worldInverseMatrix[0]'),type='matrix')
        c.connectAttr(parent+'.worldMatrix[0]',matrix+'.matrixIn[1]')
    c.connectAttr(locator+'.worldInverseMatrix[0]',matrix+'.matrixIn[2]')
    c.connectAttr(matrix+'.matrixSum',group+'.offsetParentMatrix')
