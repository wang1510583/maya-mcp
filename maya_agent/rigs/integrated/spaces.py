"""Two explicit parent spaces. Zero leaves existing local animation untouched."""


def create(control,driver,label,orientation_only=False):
    import maya.cmds as c
    short=control.rsplit('|',1)[-1]
    parent=(c.listRelatives(control,p=True,fullPath=True) or [None])[0]
    kwargs={'parent':parent} if parent else {}
    # Identity siblings preserve control channels, pivots and pre-existing curves.
    local=c.createNode('transform',name=short+'_localSpace',**kwargs)
    group=c.createNode('transform',name=short+'_spaceGrp',**kwargs)
    c.parent(control,group,relative=True)
    # Alternate target stores a maintain-offset rest pose under the chosen driver.
    alt=c.createNode('transform',name=short+'_globalSpace',parent=driver)
    c.xform(alt,ws=True,m=c.xform(local,q=True,ws=True,m=True))
    c.setAttr(local+'.visibility',False);c.setAttr(alt+'.visibility',False)
    plug=control+'.global'
    c.addAttr(control,ln='global',nn='global',at='double',min=0,max=1,dv=0,keyable=True)
    constrain=c.orientConstraint if orientation_only else c.parentConstraint
    constraint=constrain(local,alt,group,mo=False,name=short+'_spaceConstraint')[0]
    aliases=constrain(constraint,q=True,weightAliasList=True)
    reverse=c.createNode('reverse',name=short+'_spaceReverse')
    c.connectAttr(plug,reverse+'.inputX')
    c.connectAttr(reverse+'.outputX',constraint+'.'+aliases[0])
    c.connectAttr(plug,constraint+'.'+aliases[1])
    c.setAttr(constraint+'.interpType',2)
    c.addAttr(control,ln='spaceDriver',dt='string');c.setAttr(control+'.spaceDriver',driver,type='string',lock=True)
    return dict(control=control,driver=driver,group=group,constraint=constraint,attribute=plug,label=label,orientation_only=orientation_only)


def apply(built,data,world):
    result=[]
    body=built.get('body')
    chest=body['controls']['chest'] if body else world
    hips=body['controls']['hips'] if body else world
    for key,rig in built.items():
        options=data[key]['options'];ns=rig['namespace']+':'
        if key=='body' and options.get('space_chest'):result.append(create(rig['controls']['chest'],hips,'腰部'))
        elif key=='head' and options.get('space_head'):result.append(create(rig['controls']['head'],chest,'胸部',orientation_only=True))
        elif key.startswith('arm'):
            side=rig['side']
            if options.get('space_upper_arm'):result.append(create(ns+'shldrFK_'+side+'1',chest,'胸部'))
            if options.get('space_wrist'):result.append(create(ns+'handFK_'+side+'1',world,'通用根 / 世界'))
        elif key.startswith('leg'):
            if options.get('space_foot'):result.append(create(rig['controls']['foot'],hips,'腰部'))
            if options.get('space_knee'):result.append(create(rig['controls']['knee'],rig['controls']['foot'],'同侧脚腕'))
    return result
