"""Recreate a deleted generic animator without stacking its old parent driver."""
import json

TR=('translateX','translateY','translateZ','rotateX','rotateY','rotateZ')


def backup_source(target,prefix,created):
    """Independent original curves survive deletion and later controller edits."""
    import maya.cmds as c
    backup=c.createNode('network',name=prefix+'creationBackup',skipSelect=True);created.append(backup)
    c.addAttr(backup,ln='curves',at='message',multi=True)
    record=dict(node=backup,inputs={},values={})
    for i,a in enumerate(TR):
        record['values'][a]=c.getAttr(target+'.'+a)
        edge=c.connectionInfo(target+'.'+a,sfd=True)
        if edge:
            if not c.nodeType(edge.split('.')[0]).startswith('animCurveT'):
                raise ValueError('通用物件存在非普通动画驱动：'+target+'.'+a)
            curve=c.duplicate(edge.split('.')[0],name=prefix+'original_'+a)[0];created.append(curve)
            c.connectAttr(curve+'.message',backup+'.curves[%d]'%i)
            record['inputs'][a]=curve+'.output'
        else:record['inputs'][a]=''
    return record


def _write(node,attr,value):
    import maya.cmds as c
    c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,value,type='string',lock=True)


def _set_input(plug,edge,value,matrix=False):
    import maya.cmds as c
    current=c.connectionInfo(plug,sfd=True)
    if current:c.disconnectAttr(current,plug)
    if edge:c.connectAttr(edge,plug)
    elif matrix:c.setAttr(plug,*value,type='matrix')
    else:c.setAttr(plug,value)


def recreate_if_deleted(target,parent,character=None):
    import maya.cmds as c
    from . import generic_objects as go
    targets=c.ls(target,long=True) or []
    if len(targets)!=1:return None
    target=targets[0];identity=c.ls(target,uuid=True)[0]
    records=[go._data(n) for n in c.ls('::*.genericSpaceData',o=True) or []]
    matches=[r for r in records if r.get('target_uuid')==identity]
    if not matches:return None
    if len(matches)!=1:raise ValueError('通用物件存在多个登记，未自动清理。')
    old=matches[0]
    if not old.get('control_uuid') or c.ls(old['control_uuid'],long=True):return None
    if not c.undoInfo(q=True,state=True):raise ValueError('请先开启 Maya 撤销。')
    character=character or go.resolve_character(parent)
    rig_text=c.getAttr(character+'.integratedRigData');rig=json.loads(rig_text)
    if not any(r.get('owner')==old['owner'] for r in rig.get('generic_objects',[])):
        raise ValueError('旧通用绑定属于另一个角色，未自动清理。')
    if not old.get('preserve_hierarchy') or not old.get('hierarchy_driver'):
        raise ValueError('旧版通用绑定没有层级恢复记录，请先撤销删除控制器。')
    if c.referenceQuery(target,isNodeReferenced=True) or any(c.lockNode(target,q=True,lock=True)):
        raise ValueError('不能重建引用或锁定物件。')
    driver=old['hierarchy_driver'];opm=target+'.offsetParentMatrix'
    expected=driver['nodes'][-1]+'.matrixSum'
    if c.connectionInfo(opm,sfd=True)!=expected:
        raise ValueError('旧通用物件矩阵连接已被修改，未自动清理。')
    source=old.get('source_backup') or old.get('animation_transfer')
    if driver['source'] and not c.objExists(driver['source']):
        raise ValueError('原矩阵输入已丢失，不能重建。')
    state={};inputs={}
    for a in TR:
        plug=target+'.'+a
        if c.getAttr(plug,lock=True):raise ValueError('通用物件通道已锁定，未自动清理：'+plug)
        edge=c.connectionInfo(plug,sfd=True)
        if edge and not c.nodeType(edge.split('.')[0]).startswith('animCurveT'):
            raise ValueError('通用物件存在约束、动画层或外部驱动，不能直接转接：'+plug+' <- '+edge)
        inputs[a]=edge
        state[a]=c.getAttr(plug)
    current_animation=any(inputs.values())
    if source and not current_animation:
        for edge in source['inputs'].values():
            if edge and not c.objExists(edge):raise ValueError('原动画备份不完整，请先撤销删除控制器。')
    if c.getAttr(opm,lock=True):raise ValueError('通用物件矩阵已锁定。')
    # Retain backup networks and curves. Delete only registered infrastructure,
    # and refuse to remove DAG groups that now contain user-added objects.
    keep={e.split('.')[0] for e in inputs.values() if e}
    for record in (old.get('source_backup',{}),old.get('animation_transfer',{})):
        keep.update(n for n in (record.get('node'),record.get('backup')) if n)
        keep.update(e.split('.')[0] for e in record.get('inputs',{}).values() if e)
    obsolete=[n for n in old['created'] if c.objExists(n) and n not in keep and not c.nodeType(n).startswith('animCurve')]
    allowed=set(n for name in obsolete for n in c.ls(name,long=True) or [])
    panels=[]
    for handle in c.ls('::*.spaceSliderData',o=True) or []:
        entry=json.loads(c.getAttr(handle+'.spaceSliderData'))
        if entry.get('owner')==old['owner']:
            if c.referenceQuery(handle,isNodeReferenced=True) or any(c.lockNode(handle,q=True,lock=True)):
                raise ValueError('通用模式面板已锁定或引用，未自动重建。')
            panels.append((handle,entry))
    panel_nodes=set(n for handle,_ in panels for n in c.ls(handle,long=True) or [])
    for node in obsolete:
        if c.referenceQuery(node,isNodeReferenced=True) or any(c.lockNode(node,q=True,lock=True)):
            raise ValueError('旧通用节点被引用或锁定，未清理：'+node)
        for child in c.listRelatives(node,ad=True,fullPath=True) or []:
            if child not in allowed and c.nodeType(child) in ('transform','joint'):
                raise ValueError('旧通用组包含其他物件，未清理：'+child)
        for dst in c.listConnections(node,s=False,d=True,p=True) or []:
            other=dst.split('.')[0];path=(c.ls(other,long=True) or [other])[0]
            if path in allowed or path in panel_nodes or other in keep or path==target:continue
            if c.nodeType(other)=='multDoubleLinear' and 'switchPosition_generic_' in other:continue
            if c.nodeType(other) in ('displayLayer','nodeGraphEditorInfo'):continue
            raise ValueError('旧通用节点仍驱动其他物件，未自动清理：'+dst)
    marker=target+'.genericSpaceOwner';marker_source=c.connectionInfo(marker,sfd=True)
    if marker_source!=old['owner']+'.message':raise ValueError('通用登记连接不一致，未清理。')
    frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    original_opm=c.getAttr(opm);result=None
    c.undoInfo(openChunk=True,chunkName='RecreateDeletedGenericControl');c.autoKeyframe(state=False)
    try:
        # Current ordinary keys supersede historical creation backups. Capture
        # their world poses before removing the obsolete virtual-parent input.
        from .generic_animation import capture
        poses=capture(target) if current_animation else None
        _set_input(opm,driver['source'],driver['matrix'],True)
        if source and not current_animation:
            for a in TR:_set_input(target+'.'+a,source['inputs'].get(a,''),source['values'][a])
        c.disconnectAttr(marker_source,marker)
        rig['generic_objects']=[r for r in rig['generic_objects'] if r['owner']!=old['owner']]
        _write(character,'integratedRigData',json.dumps(rig,ensure_ascii=False))
        # Keep old nodes untouched until all new-controller pose checks pass.
        number=max([old['number']]+[r['number'] for r in records])+1
        while c.objExists(rig['namespace']+':generic%02d_mode'%number):number+=1
        result=go._add_new(target,parent,character,_number=old['number'],_node_number=number,_ignored_owner=old['owner'],_pose_samples=poses)
    except Exception:
        # _add_new has its own rollback. Restore the detached old registration
        # and exact channel state; no old node has been deleted at this stage.
        for a in TR:_set_input(target+'.'+a,inputs[a],state[a])
        _set_input(opm,expected,original_opm,True)
        current=c.connectionInfo(marker,sfd=True)
        if current:c.disconnectAttr(current,marker)
        c.connectAttr(marker_source,marker)
        _write(character,'integratedRigData',rig_text)
        raise
    finally:
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select([n for n in selection if c.objExists(n)],r=True) if selection else c.select(clear=True)
        c.undoInfo(closeChunk=True)
    # Rebind an existing mode-panel row before deleting its old owner.
    # Separate chunk still lives inside the UI/MCP calling transaction.
    c.undoInfo(openChunk=True,chunkName='RetireDeletedGenericControl')
    try:
        from maya_agent.rigs import switch_panel
        for handle,entry in panels:
            c.connectAttr(result['owner']+'.message',handle+'.switchOwner',force=True)
            if c.objExists(handle+'.global'):c.deleteAttr(handle+'.global')
            c.addAttr(handle,ln='global',proxy=result['global_plug'],keyable=True)
            for dst in c.listConnections(old['global_plug'],s=False,d=True,p=True) or []:
                if c.nodeType(dst.split('.')[0])=='multDoubleLinear' and 'switchPosition_' in dst:
                    c.connectAttr(result['global_plug'],dst,force=True)
            entry.update(owner=result['owner'],plug=result['global_plug'])
            _write(handle,'spaceSliderData',json.dumps(entry))
            switch_panel._key_proxies(handle)
        if obsolete:c.delete(obsolete)
    finally:c.undoInfo(closeChunk=True)
    result['recreated']=True
    return result
