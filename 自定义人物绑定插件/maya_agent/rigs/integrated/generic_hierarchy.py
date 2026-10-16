"""Drive a prop's virtual parent without moving the original DAG or geometry."""
import json


def orphan_chain(source,target):
    """Recognize only this tool's abandoned parent drivers, never arbitrary DG."""
    import re
    import maya.cmds as c
    parent=(c.listRelatives(target,p=True,f=True) or [None])[0]
    identity=c.ls(target,uuid=True)[0];chain=[];seen=set()
    while source and source not in seen:
        seen.add(source);node,attr=source.split('.',1)
        if attr!='matrixSum' or c.nodeType(node)!='multMatrix':break
        if not re.search(r'(^|:)generic\d+_preserveParent$',node):break
        prefix=node.rsplit('_preserveParent',1)[0];hold=prefix+'_originalParentOffset'
        if c.objExists(prefix+'_mode') or c.connectionInfo(node+'.matrixIn[1]',sfd=True):break
        if c.objExists(node+'.genericTargetUuid') and c.getAttr(node+'.genericTargetUuid')!=identity:break
        if not c.objExists(hold) or c.nodeType(hold)!='holdMatrix':break
        if c.connectionInfo(node+'.matrixIn[0]',sfd=True)!=hold+'.outMatrix':break
        inverse=c.connectionInfo(node+'.matrixIn[2]',sfd=True)
        if parent:
            if not inverse or not inverse.split('.',1)[1].startswith('worldInverseMatrix'):break
            if c.ls(inverse.split('.')[0],l=True)!=[parent]:break
        elif inverse:break
        chain.append(node)
        source=c.connectionInfo(hold+'.inMatrix',sfd=True)
    return chain,source


def connect_clean_source(source,value,destination,target,prefix,nodes):
    """Drop abandoned parent motion, retaining the pose and original OPM animation."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    chain,base=orphan_chain(source,target) if source else ([],None)
    if not chain:
        if source:c.connectAttr(source,destination,force=True)
        else:c.setAttr(destination,*value,type='matrix')
        return []
    if base:
        # Keep genuine upstream animation; only the obsolete rig's parent
        # motion is replaced by a constant frame offset captured at this pose.
        current=om.MMatrix(c.getAttr(base));offset=current.inverse()*om.MMatrix(value)
        clean=c.createNode('multMatrix',name=prefix+'_rebuildOffset');nodes.append(clean)
        c.connectAttr(base,clean+'.matrixIn[0]');c.setAttr(clean+'.matrixIn[1]',*list(offset),type='matrix')
        c.connectAttr(clean+'.matrixSum',destination,force=True)
    else:
        edge=c.connectionInfo(destination,sfd=True)
        if edge:c.disconnectAttr(edge,destination)
        c.setAttr(destination,*value,type='matrix')
    return chain


def install_driver(data,target,control):
    import maya.cmds as c
    plug=target+'.offsetParentMatrix'
    if c.getAttr(plug,lock=True):raise ValueError('通用物件的 offsetParentMatrix 已锁定。')
    parent=(c.listRelatives(target,p=True,f=True) or [None])[0]
    record=dict(source=c.connectionInfo(plug,sfd=True),matrix=c.getAttr(plug),
                control_source=c.connectionInfo(control+'.offsetParentMatrix',sfd=True),
                control_matrix=c.getAttr(control+'.offsetParentMatrix'),nodes=[])
    prefix=data['owner'].rsplit('_mode',1)[0]
    try:
        # Isolate the original OPM input before the driven OPM replaces it.
        source=c.createNode('holdMatrix',name=prefix+'_originalParentOffset');record['nodes'].append(source)
        record['removed_orphan_inputs']=connect_clean_source(record['source'],record['matrix'],source+'.inMatrix',target,prefix,record['nodes'])
        c.connectAttr(source+'.outMatrix',control+'.offsetParentMatrix',force=True)
        matrix=c.createNode('multMatrix',name=prefix+'_preserveParent');record['nodes'].append(matrix)
        c.addAttr(matrix,ln='genericTargetUuid',dt='string');c.setAttr(matrix+'.genericTargetUuid',c.ls(target,uuid=True)[0],type='string',lock=True)
        c.connectAttr(source+'.outMatrix',matrix+'.matrixIn[0]')
        c.connectAttr(data['compensation']+'.worldMatrix[0]',matrix+'.matrixIn[1]')
        # Do not use target.parentInverseMatrix: it includes the driven OPM.
        if parent:c.connectAttr(parent+'.worldInverseMatrix[0]',matrix+'.matrixIn[2]')
        c.connectAttr(matrix+'.matrixSum',plug,force=True)
        return record
    except Exception:
        remove_driver(record,target,control)
        raise


def repair_orphan_input(character,owner):
    """Repair a live prop rebuilt on top of an abandoned generic parent graph."""
    import maya.cmds as c
    from .generic_objects import _data
    data=_data(owner);target=c.ls(data['target_uuid'],l=True)[0]
    prefix=owner.rsplit('_mode',1)[0];plug=prefix+'_originalParentOffset.inMatrix'
    source=c.connectionInfo(plug,sfd=True);value=c.getAttr(plug)
    chain,base=orphan_chain(source,target) if source else ([],None)
    if not chain:return dict(changed=False)
    before=c.xform(target,q=True,ws=True,m=True);nodes=[]
    owner_before=c.getAttr(owner+'.genericSpaceData');rig_before=c.getAttr(character+'.integratedRigData')
    auto=c.autoKeyframe(q=True,state=True);c.undoInfo(openChunk=True,chunkName='RepairGenericRebuild');c.autoKeyframe(state=False)
    try:
        connect_clean_source(source,value,plug,target,prefix,nodes)
        error=max(abs(a-b) for a,b in zip(before,c.xform(target,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('清理旧通用驱动未保留姿态：'+str(error))
        data.setdefault('orphan_repairs',[]).append(dict(source=source,matrix=value,ignored=chain,nodes=nodes))
        data['created']+=nodes
        rig=json.loads(rig_before);rig['generic_objects']=[data if r['target_uuid']==data['target_uuid'] else r for r in rig['generic_objects']]
        for node,attr,text in ((owner,'genericSpaceData',json.dumps(data)),(character,'integratedRigData',json.dumps(rig,ensure_ascii=False))):
            c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,text,type='string',lock=True)
        return dict(changed=True,ignored=chain,max_pose_error=error)
    except Exception:
        c.connectAttr(source,plug,force=True)
        for node in reversed(nodes):
            if c.objExists(node):c.delete(node)
        for node,attr,text in ((owner,'genericSpaceData',owner_before),(character,'integratedRigData',rig_before)):
            c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,text,type='string',lock=True)
        raise
    finally:c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)


def remove_driver(record,target,control):
    import maya.cmds as c
    for node,source,matrix in ((target,record['source'],record['matrix']),
                               (control,record['control_source'],record['control_matrix'])):
        plug=node+'.offsetParentMatrix';edge=c.connectionInfo(plug,sfd=True)
        if edge:c.disconnectAttr(edge,plug)
        if source:c.connectAttr(source,plug,force=True)
        else:c.setAttr(plug,*matrix,type='matrix')
    for node in reversed(record['nodes']):
        if c.objExists(node):c.delete(node)


def restore_original_parent(character,owner):
    """Explicit migration of a legacy prop, keeping its controller and curves."""
    import maya.cmds as c
    from .generic_objects import _data
    data=_data(owner)
    if data.get('preserve_hierarchy'):return data
    target=(c.ls(data['target_uuid'],l=True) or [None])[0]
    control=(c.ls(data.get('control_uuid',''),l=True) or [None])[0]
    if not target or not control:raise ValueError('通用物件或控制器缺失，不能恢复层级。')
    parent=data.get('original_parent')
    if data.get('original_parent_uuid'):
        matches=c.ls(data['original_parent_uuid'],l=True) or []
        if len(matches)!=1:raise ValueError('通用物件的原父物体已删除。')
        parent=matches[0]
    elif parent and not c.objExists(parent):raise ValueError('通用物件的原父物体已删除或改名：'+parent)
    old_parent=(c.listRelatives(target,p=True,f=True) or [None])[0]
    if old_parent!=(c.ls(data['compensation'],l=True) or [None])[0]:
        raise ValueError('通用物件的层级已手动改变，不能自动迁移。')
    if parent and (parent==target or parent.startswith(target+'|')):raise ValueError('原父级会产生循环。')
    pose=c.xform(target,q=True,ws=True,m=True)
    metadata=c.getAttr(character+'.integratedRigData');owner_data=c.getAttr(owner+'.genericSpaceData')
    auto=c.autoKeyframe(q=True,state=True);selection=[c.ls(n,uuid=True)[0] for n in c.ls(sl=True,l=True) or []]
    record=None;moved=False;c.undoInfo(openChunk=True,chunkName='PreserveGenericObjectHierarchy');c.autoKeyframe(state=False)
    try:
        kwargs=dict(relative=True,noInvScale=True)
        if parent:c.parent(target,parent,**kwargs)
        else:c.parent(target,world=True,**kwargs)
        moved=True;target=c.ls(data['target_uuid'],l=True)[0]
        record=install_driver(data,target,control)
        error=max(abs(a-b) for a,b in zip(pose,c.xform(target,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('恢复原层级未保留姿态：'+str(error))
        data.update(target=target,preserve_hierarchy=True,hierarchy_driver=record,
                    original_parent_uuid=c.ls(parent,uuid=True)[0] if parent else None)
        data['created']+=record['nodes']
        rig=json.loads(metadata);rig['generic_objects']=[data if r['target_uuid']==data['target_uuid'] else r for r in rig['generic_objects']]
        for node,attr,value in ((character,'integratedRigData',json.dumps(rig,ensure_ascii=False)),(owner,'genericSpaceData',json.dumps(data))):
            c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,value,type='string',lock=True)
        return data
    except Exception:
        if record:remove_driver(record,target,control)
        if moved:c.parent(target,old_parent,relative=True,noInvScale=True)
        for node,attr,value in ((character,'integratedRigData',metadata),(owner,'genericSpaceData',owner_data)):
            c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,value,type='string',lock=True)
        raise
    finally:
        selected=[n for identity in selection for n in c.ls(identity,l=True) or []]
        c.select(selected,r=True) if selected else c.select(cl=True)
        c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)
