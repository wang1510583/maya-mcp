"""Reference hierarchy: isolated limb groups, clavicle and hip point followers."""


def sampled_reference(driver,item,namespace,root,name):
    import maya.cmds as c
    from .builder import root_reference
    frame=c.currentTime(q=True);motion={}
    try:
        for f in sorted(set(item['frames'])|{frame}):
            c.currentTime(f);motion[f]=c.xform(driver,q=True,ws=True,m=True)
    finally:c.currentTime(frame)
    reference=root_reference(namespace,root,motion,bool(item['frames']),name)
    c.setAttr(reference+'.inheritsTransform',False)
    return reference


def apply(built,data,root):
    import maya.cmds as c
    body=built.get('body');pending=[];links=[]
    for key,rig in built.items():
        if key.startswith('shoulder_') and body:
            chest=body['controls']['chest'];ctrl=rig['controls']['clavicle']
            zero=c.listRelatives(ctrl,p=True,fullPath=True)[0]
            ref=sampled_reference(chest,data[key],rig['namespace'],root,'chest_attachment_reference')
            group=c.createNode('transform',name=rig['namespace']+':chest_attachment',parent=chest)
            c.connectAttr(ref+'.worldInverseMatrix[0]',group+'.offsetParentMatrix')
            c.parent(zero,group,relative=True)
            rig['control_attachment']=dict(group=group,parent=chest,reference=ref)
            links.append(dict(part=key,mode='clavicle_under_chest',driver=chest))
    for key,rig in built.items():
        if key.startswith('arm_'):
            shoulder=built.get('shoulder_'+rig['side'])
            driver=shoulder['controls']['clavicle'] if shoulder else body['controls']['chest'] if body else None
            control=rig['controls']['shoulder_fk'];label='shoulder'
        elif key.startswith('leg_'):
            driver=body['controls']['hips'] if body else None
            control=rig['controls']['hip'];label='hip'
        else:continue
        if not driver:continue
        locator=c.spaceLocator(name=rig['namespace']+':'+label+'_locator')[0]
        c.parent(locator,root)
        c.xform(locator,ws=True,m=c.xform(control,q=True,ws=True,m=True))
        c.parentConstraint(driver,locator,mo=True,name=rig['namespace']+':'+label+'_locatorConstraint')
        for shape in c.listRelatives(locator,s=True) or []:c.setAttr(shape+'.visibility',False)
        rig[label+'_locator']=locator
        pending.append((key,control,locator,label))
        links.append(dict(part=key,mode=label+'_point_only',driver=driver))
    return links,pending


def finish(built,data,root,pending):
    # Space groups precede point groups so position remains driven by the
    # attachment, while global independently changes upper-arm orientation.
    from .attachments import point_link
    for key,control,locator,label in pending:
        point_link(built[key],data[key],root,control=control,locator=locator,label=label)
