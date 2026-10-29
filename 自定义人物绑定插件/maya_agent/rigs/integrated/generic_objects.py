"""Appendable props with parent/master spaces and pose-preserving switches."""
from maya_agent.rigs import scene_data
import json


def ensure_controller(character,owner,pose_samples=None):
    """Add a native box animator in its switching space, retaining prop curves.

    TR inputs move to the animator without changing their values. Other local
    frame attributes are shared from the prop so joints, pivots and OPM behave
    identically. No world-matrix feedback or evaluation callbacks are needed.
    """
    import math
    import maya.cmds as c
    from maya_agent.rigs import controller_shapes
    data=_data(owner)
    if data.get('control_uuid'):
        found=c.ls(data['control_uuid'],l=True) or []
        if len(found)!=1:raise ValueError('通用控制器已被删除，请先撤销删除或恢复控制器。')
        from .generic_keys import expose_matches
        expose_matches(found[0],data)
        return data
    found=c.ls(data['target_uuid'],l=True) or []
    if len(found)!=1:raise ValueError('通用物件已删除或不唯一。')
    target=found[0];parent=data['compensation'] if data.get('preserve_hierarchy') else (c.listRelatives(target,p=True,f=True) or [None])[0]
    if not parent:raise ValueError('通用物件的空间层级已改变，请先恢复。')
    if c.referenceQuery(target,isNodeReferenced=True) or any(c.lockNode(target,q=True,lock=True)):
        raise ValueError('不能为引用或锁定的通用物件添加控制器。')
    channels=('tx','ty','tz','rx','ry','rz');inputs={};values={};locked={}
    for a in channels:
        plug=target+'.'+a;inputs[a]=c.connectionInfo(plug,sfd=True);values[a]=c.getAttr(plug);locked[a]=c.getAttr(plug,lock=True)
        if inputs[a] and not c.nodeType(inputs[a].split('.')[0]).startswith('animCurveT'):
            raise ValueError('通用物件通道已有外部驱动或动画层，不能直接转接：'+plug)
    before=pose_samples[c.currentTime(q=True)] if pose_samples else c.xform(target,q=True,ws=True,m=True)
    old_owner=c.getAttr(owner+'.genericSpaceData');old_rig=c.getAttr(character+'.integratedRigData')
    selection=[c.ls(n,uuid=True)[0] for n in c.ls(sl=True,l=True) or []]
    auto=c.autoKeyframe(q=True,state=True);control=None;transferred=[];driver=None;animation_receipt=None
    c.undoInfo(openChunk=True,chunkName='CreateGenericBoxControl');c.autoKeyframe(state=False)
    try:
        prefix=owner.rsplit('_mode',1)[0]
        control=c.createNode(c.nodeType(target),name=prefix+'_ctrl',parent=parent)
        if c.nodeType(target)=='joint':c.setAttr(control+'.drawStyle',2)
        shared=['scale','shear','rotateOrder','rotateAxis','rotatePivot','rotatePivotTranslate',
                'scalePivot','scalePivotTranslate','offsetParentMatrix','inheritsTransform','visibility']
        if c.nodeType(target)=='joint':shared+=['jointOrient','segmentScaleCompensate','inverseScale']
        for attr in shared:c.connectAttr(target+'.'+attr,control+'.'+attr,force=True)
        for a in channels:
            c.setAttr(control+'.'+a,values[a])
            if locked[a]:c.setAttr(control+'.'+a,lock=True,keyable=False);continue
            transferred.append(a)
            if inputs[a]:
                c.disconnectAttr(inputs[a],target+'.'+a);c.connectAttr(inputs[a],control+'.'+a)
                # Reconnecting a curve evaluates it and can discard an unsaved
                # native channel override. Preserve the creation-frame pose.
                c.setAttr(control+'.'+a,values[a])
            c.connectAttr(control+'.'+a,target+'.'+a)
            c.setAttr(control+'.'+a,keyable=c.getAttr(target+'.'+a,keyable=True))
        for a in ('sx','sy','sz','v'):c.setAttr(control+'.'+a,keyable=False,channelBox=False,lock=True)
        bounds=c.exactWorldBoundingBox(target)
        extent=max(bounds[i+3]-bounds[i] for i in range(3))
        fallback=max(2.,c.getAttr(target+'.radius')*4) if c.nodeType(target)=='joint' else 4.
        size=extent*1.15 if math.isfinite(extent) and 1e-5<extent<1e10 else fallback
        artwork=json.loads(controller_shapes.DATA.read_text(encoding='utf-8'))['parts']['body']
        points=[p for s in artwork['controls']['hips']['shapes'] for p in s.get('points',[])]
        width=max(max(p[i] for p in points)-min(p[i] for p in points) for i in range(3))
        metrics=dict(lengths=[size/width*sum(artwork['metrics']['lengths'])])
        shaped=dict(namespace=owner.rsplit(':',1)[0],controls={'hips':control})
        appearance=controller_shapes.apply(shaped,'body',metrics=metrics)
        c.addAttr(control,ln='global',nn='通用模式',proxy=data['global_plug'],keyable=True)
        c.addAttr(control,ln='genericSpaceOwner',at='message');c.connectAttr(owner+'.message',control+'.genericSpaceOwner')
        from .generic_keys import expose_matches
        expose_matches(control,data)
        if data.get('preserve_hierarchy'):
            from .generic_hierarchy import install_driver
            driver=install_driver(data,target,control)
            data['hierarchy_driver']=driver
            data['created']+=driver['nodes']
        if pose_samples:
            from .generic_animation import bake
            animation_receipt=bake(data,control,pose_samples)
            if animation_receipt:
                data['animation_transfer']=animation_receipt
                data['created']+=animation_receipt['nodes']
        # These are native channels: S/autokey and Maya's move/rotate tools work
        # directly, including non-zero joint orientations and animated pivots.
        if max(abs(a-b) for a,b in zip(before,c.xform(target,q=True,ws=True,m=True)))>1e-5:
            raise RuntimeError('添加控制器改变了通用物件姿态，已回退。')
        if max(abs(a-b) for a,b in zip(before,c.xform(control,q=True,ws=True,m=True)))>1e-5:
            raise RuntimeError('通用控制器与物件的局部坐标不一致，已回退。')
        data.update(control=control,control_uuid=c.ls(control,uuid=True)[0],control_version='1.0.0',control_appearance=appearance)
        data['created']=list(data['created'])+[control]+shaped.get('nodes',[])
        c.setAttr(owner+'.genericSpaceData',lock=False);c.setAttr(owner+'.genericSpaceData',json.dumps(data),type='string',lock=True)
        rig=json.loads(old_rig)
        rig['generic_objects']=[data if r['target_uuid']==data['target_uuid'] else r for r in rig['generic_objects']]
        c.setAttr(character+'.integratedRigData',lock=False);c.setAttr(character+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
        return data
    except Exception:
        if animation_receipt:
            from .generic_animation import restore as restore_animation
            restore_animation(control,animation_receipt)
        if driver:
            from .generic_hierarchy import remove_driver
            remove_driver(driver,target,control)
        for a in transferred:
            dst=target+'.'+a;source=c.connectionInfo(dst,sfd=True)
            if source:c.disconnectAttr(source,dst)
            if inputs[a]:
                if c.isConnected(inputs[a],control+'.'+a):c.disconnectAttr(inputs[a],control+'.'+a)
                c.connectAttr(inputs[a],dst,force=True)
            else:c.setAttr(dst,values[a])
        for node,attr,value in ((owner,'genericSpaceData',old_owner),(character,'integratedRigData',old_rig)):
            c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,value,type='string',lock=True)
        if control and c.objExists(control):c.delete(control)
        raise
    finally:
        c.autoKeyframe(state=auto)
        selected=[n for identity in selection for n in c.ls(identity,l=True) or []]
        c.select(selected,r=True) if selected else c.select(cl=True)
        c.undoInfo(closeChunk=True)


def upgrade_controls(character):
    import maya.cmds as c
    rig=scene_data.read(character+'.integratedRigData')
    c.undoInfo(openChunk=True,chunkName='UpgradeGenericControls')
    try:return [ensure_controller(character,row['owner']) for row in rig.get('generic_objects',[])]
    finally:c.undoInfo(closeChunk=True)


def _data(owner):
    import maya.cmds as c
    return scene_data.read(owner+'.genericSpaceData')


def resolve_character(parent):
    import maya.cmds as c
    roots=c.ls('*.integratedRigData','*:*.integratedRigData',o=True,l=True) or []
    path=c.ls(parent,l=True)[0]; candidates=[]
    for root in roots:
        rig=scene_data.read(root+'.integratedRigData')
        nodes=[root,rig.get('master_control')]+[p['root'] for p in rig['parts'].values()]
        targets=[m['target'] for p in rig['parts'].values() for m in p.get('original_target_mapping',[])]
        paths=[c.ls(n,l=True)[0] for n in nodes+targets if n and c.objExists(n)]
        if any(path==p or path.startswith(p+'|') for p in paths):candidates.append(root)
    if len(candidates)==1:return candidates[0]
    if len(roots)==1:return roots[0]
    raise ValueError('无法确定通用物件所属角色，请载入该角色内的根物体。')


def add(target,parent,character=None):
    import maya.cmds as c
    from .generic_rebuild import recreate_if_deleted
    c.undoInfo(openChunk=True,chunkName='AddOrRecreateGenericObject')
    try:
        restored=recreate_if_deleted(target,parent,character)
        return restored if restored is not None else _add_new(target,parent,character)
    finally:c.undoInfo(closeChunk=True)


def _add_new(target,parent,character=None,_number=None,_node_number=None,_ignored_owner=None,_pose_samples=None):
    import maya.cmds as c
    from .master_control import upgrade
    def unique(n):
        rows=c.ls(n,l=True) or []
        if len(rows)!=1 or c.nodeType(rows[0]) not in ('transform','joint'):raise ValueError('只能载入一个物体。')
        return rows[0]
    target=unique(target);parent=unique(parent)
    if parent==target or parent.startswith(target+'|'):raise ValueError('根物体不能是通用物件本身或它的子级。')
    if c.referenceQuery(target,isNodeReferenced=True) or any(c.lockNode(target,q=True,lock=True)):
        raise ValueError('不能重排引用或锁定物体的层级。')
    if not c.getAttr(target+'.inheritsTransform'):raise ValueError('通用物件必须开启继承变换。')
    marker_exists=c.objExists(target+'.genericSpaceOwner')
    if marker_exists:
        # Removing a rig leaves its message attribute on the original prop.
        # An empty marker is not a registration; reuse it transactionally.
        marker=target+'.genericSpaceOwner'
        if c.getAttr(marker,type=True)!='message' or c.getAttr(marker,lock=True):
            raise ValueError('通用物件登记属性类型不正确或已锁定：'+marker)
        if c.listConnections(marker,s=True,d=True,p=True):
            raise ValueError('此物件已连接通用绑定，不能重复创建。')
    if not c.undoInfo(q=True,state=True):raise ValueError('请先开启 Maya 撤销。')
    character=character or resolve_character(parent)
    rig=scene_data.read(character+'.integratedRigData')
    identity=c.ls(target,uuid=True)[0]
    for owner in c.ls('::*.genericSpaceData',o=True) or []:
        if owner==_ignored_owner:continue
        record=_data(owner)
        if identity in (record.get('target_uuid'),record.get('control_uuid')):
            raise ValueError('此物件仍有有效通用绑定登记，不能重复创建：'+owner)
    for row in rig.get('generic_objects',[]):
        if row['target_uuid']==identity:raise ValueError('此物件已经添加，请勿重复创建。')
    owned=[character]+[p['root'] for p in rig['parts'].values()]
    owned += [n for p in rig['parts'].values() for key in ('controls','zero_controls','live_controls') for n in p.get(key,{}).values()]
    owned += [m['target'] for p in rig['parts'].values() for m in p.get('original_target_mapping',[])]
    owned += [rig.get('master_control')]
    for node in owned:
        if node and c.objExists(node):
            path=unique(node)
            if path==target or path.startswith(target+'|'):raise ValueError('不能把角色根、已有求解骨骼或总控制圆环作为通用物件。')
    for attr in ('tx','ty','tz','rx','ry','rz'):
        source=c.connectionInfo(target+'.'+attr,sfd=True)
        if source and not c.nodeType(source.split('.')[0]).startswith('animCurve'):
            raise ValueError('通用物件已有约束或驱动，不能改变其层级：'+target+'.'+attr)
    original_parent=(c.listRelatives(target,p=True,f=True) or [None])[0]
    from .generic_animation import capture,has_animation
    pose_samples=_pose_samples if _pose_samples is not None else (capture(target) if has_animation(target) else None)
    before=c.xform(target,q=True,ws=True,m=True)
    parent_matrix=c.xform(original_parent,q=True,ws=True,m=True) if original_parent else [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
    selection=c.ls(sl=True,l=True) or [];selection_ids=[c.ls(n,uuid=True)[0] for n in selection]
    auto=c.autoKeyframe(q=True,state=True);created=[];metadata_before=None
    c.undoInfo(openChunk=True,chunkName='AddGenericObject');c.autoKeyframe(state=False)
    try:
        master=upgrade(character)['control']
        metadata_before=c.getAttr(character+'.integratedRigData')
        master_path=unique(master)
        if master_path.startswith(target+'|'):raise ValueError('通用物件不能包含总控制圆环。')
        number=_number or max([0]+[r['number'] for r in rig.get('generic_objects',[])])+1
        prefix=rig['namespace']+':generic%02d_'%(_node_number or number)
        def node(kind,name,**kwargs):
            n=c.createNode(kind,name=prefix+name,**kwargs);created.append(n);return n
        local=node('transform','parentSpace',parent=parent);c.xform(local,ws=True,m=parent_matrix)
        alternate=node('transform','masterSpace',parent=master);c.xform(alternate,ws=True,m=parent_matrix)
        group=node('transform','space',parent=parent)
        constraint=c.parentConstraint(local,alternate,group,mo=False)[0];created.append(constraint)
        weights=c.parentConstraint(constraint,q=True,wal=True)
        owner=node('transform','mode',parent=character);c.setAttr(owner+'.visibility',False)
        c.addAttr(owner,ln='global',nn='通用'+str(number),at='enum',en='父物体:总圆环',keyable=True)
        reverse=node('reverse','reverse');c.connectAttr(owner+'.global',reverse+'.inputX')
        c.connectAttr(reverse+'.outputX',constraint+'.'+weights[0]);c.connectAttr(owner+'.global',constraint+'.'+weights[1])
        # Two mode-specific offsets preserve the pose without touching prop keys.
        offsets=[]
        choice=node('choice','offsetChoice');c.connectAttr(owner+'.global',choice+'.selector')
        for i in range(2):
            offset=node('transform','offset'+str(i),parent=owner);offsets.append(offset)
            c.connectAttr(offset+'.matrix',choice+'.input[%d]'%i)
        compensation=node('transform','match',parent=group)
        c.connectAttr(choice+'.output',compensation+'.offsetParentMatrix')
        # Only the controller lives in the switching space. The original prop
        # stays under its existing parent, with a native matrix parent driver.
        error=max(abs(a-b) for a,b in zip(before,c.xform(target,q=True,ws=True,m=True)))
        if error>1e-5:raise ValueError('通用物件存在不支持的缩放或变换，创建已回退：%g'%error)
        data=dict(number=number,target_uuid=identity,target=target,parent_uuid=c.ls(parent,uuid=True)[0],
                  control=target,global_plug=owner+'.global',group=group,compensation=compensation,offsets=offsets,
                  owner=owner,master=master,original_parent=original_parent,created=created,
                  original_parent_uuid=c.ls(original_parent,uuid=True)[0] if original_parent else None,preserve_hierarchy=True)
        from .generic_rebuild import backup_source
        data['source_backup']=backup_source(target,prefix,created)
        c.addAttr(owner,ln='genericSpaceData',dt='string');c.setAttr(owner+'.genericSpaceData',json.dumps(data),type='string',lock=True)
        if not marker_exists:c.addAttr(target,ln='genericSpaceOwner',at='message')
        c.connectAttr(owner+'.message',target+'.genericSpaceOwner')
        rig=scene_data.read(character+'.integratedRigData');rig.setdefault('generic_objects',[]).append(data)
        c.setAttr(character+'.integratedRigData',lock=False);c.setAttr(character+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
        from maya_agent.rigs import arm_ik
        arm_ik.install()
        return ensure_controller(character,owner,pose_samples=pose_samples)
    except Exception:
        if metadata_before is not None:
            c.setAttr(character+'.integratedRigData',lock=False)
            c.setAttr(character+'.integratedRigData',metadata_before,type='string',lock=True)
        if c.objExists(target+'.genericSpaceOwner') and not marker_exists:c.deleteAttr(target+'.genericSpaceOwner')
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        raise
    finally:
        selected=[n for identity in selection_ids for n in c.ls(identity,l=True) or []]
        c.select(selected,r=True) if selected else c.select(cl=True)
        c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)


def _hold_stale_matches(plug,offset):
    """A new space event owns its match until the next explicit mode key.

    Public mode keys can be removed/overwritten without deleting the hidden
    matching keys. Those orphaned values must not move an otherwise held prop.
    Only update this destination's implementation channels, never prop animation
    or offsets at/after a future authored mode event.
    """
    import maya.cmds as c
    from maya_agent.rigs import live_edit,live_layers
    now=c.currentTime(q=True)
    future=[t for curve in live_layers.curves_for_plug(plug)
            for t in c.keyframe(curve,q=True,tc=True) or [] if t>now]
    end=min(future) if future else float('inf')
    for attr in live_edit.TR:
        for curve in live_layers.curves_for_plug(offset+'.'+attr):
            held=c.keyframe(curve,q=True,eval=True,time=(now,now))[0]
            for t in c.keyframe(curve,q=True,tc=True) or []:
                if now<t<end:c.keyframe(curve,e=True,time=(t,t),vc=held)


def switch(owner,value,key=None,previous=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from maya_agent.rigs import arm_ik
    data=_data(owner);plug=data['global_plug'];value=int(bool(value))
    old=int(c.getAttr(plug)) if previous is None else int(previous)
    if value==old:return data
    auto=c.autoKeyframe(q=True,state=True);key=auto if key is None else key
    from maya_agent.rigs import live_edit,live_layers
    busy=arm_ik._busy;arm_ik._busy=True;c.undoInfo(openChunk=True,chunkName='SwitchGenericSpace');c.autoKeyframe(state=False)
    snapshot=None;edges={}
    try:
        fences=[];live_edit._fence('before',fences)
        c.setAttr(plug,old)
        offset=data['offsets'][value]
        plugs=[offset+'.'+attr for attr in live_edit.TR]+[plug]
        snapshot=live_edit._snapshot(plugs);fences.append(snapshot)
        world=om.MMatrix(c.xform(data['compensation'],q=True,ws=True,m=True))
        edges={p:c.connectionInfo(p,sfd=True) for p in plugs if p!=plug}
        edges={p:e for p,e in edges.items() if e}
        for p,e in edges.items():c.disconnectAttr(e,p);c.setAttr(p,snapshot[0][p])
        c.setAttr(plug,value)
        parent=om.MMatrix(c.xform(data['group'],q=True,ws=True,m=True))
        local=world*parent.inverse()
        c.xform(offset,os=True,m=list(local))
        values={p:c.getAttr(p) for p in plugs}
        for p,e in edges.items():c.connectAttr(e,p)
        for p,v in values.items():c.setAttr(p,v)
        result=om.MMatrix(c.xform(data['compensation'],q=True,ws=True,m=True))
        if max(abs(a-b) for a,b in zip(world,result))>1e-5:raise RuntimeError('通用空间切换未能保持姿态。')
        if key:
            # New hidden channels need a baseline so a later switch does not
            # retroactively offset the earlier use of the same parent space.
            start=min(c.playbackOptions(q=True,animationStartTime=True),c.currentTime(q=True))
            if start<c.currentTime(q=True):
                for p,old_value in snapshot[0].items():
                    if not c.keyframe(p,q=True,kc=True):c.setKeyframe(p,t=start,v=old_value,itt='auto',ott='step')
            for p,v in values.items():c.setAttr(p,v)
            # Every component must have a hold key, even if it equals the old
            # value, otherwise a reused destination can inherit an older key.
            live_layers.key_mode_switch(snapshot,plug,plugs)
            _hold_stale_matches(plug,offset)
            for p in plugs:
                curves=c.listConnections(p,s=True,d=False,type='animCurve') or []
                if curves:c.keyTangent(curves,e=True,ott='step')
        live_edit._fence('after',[live_edit._snapshot(plugs)])
        return data
    except Exception:
        for p,e in edges.items():
            if not c.isConnected(e,p):c.connectAttr(e,p,force=True)
        if snapshot:live_edit._restore(snapshot)
        else:c.setAttr(plug,old)
        raise
    finally:
        arm_ik._busy=busy;c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True);arm_ik._sync_mode_cache()
