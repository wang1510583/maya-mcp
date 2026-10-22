"""Validated mobile key import. No scene save; preflight, backup and undo on failure."""
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime
import maya.cmds as cmds

ATTRS = ('rotateX','rotateY','rotateZ','translateX','translateY','translateZ')
ATTR_NAME = __import__('re').compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

def number(v):
    if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v):
        raise ValueError('无效通道数值')
    return float(v)

def resolve(uid):
    try:
        nodes=cmds.ls(uid,long=True) or []  # uuid=True would return identifiers, not paths.
    except RuntimeError as exc:
        raise ValueError('无效或不存在的 UUID: '+str(uid)) from exc
    if len(nodes)!=1: raise ValueError('UUID 未唯一匹配: '+str(uid))
    return nodes[0]

def driven_attribute_target(node, attr):
    """Return the writable source plug for a mirrored zero/control attribute."""
    plug=node+'.'+attr
    for source in cmds.listConnections(plug,source=True,destination=False,plugs=True) or []:
        source_node,sep,source_attr=source.rpartition('.')
        if sep and source_attr==attr and cmds.objExists(source_node) and cmds.attributeQuery(attr,node=source_node,exists=True):
            return source
    return plug

def apply(path,dry_run=False,snapshot_path=None,backup_directory=None):
    package=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if package.get('format')!='maya-mobile-animation' or package.get('schemaVersion')!=1:
        raise ValueError('不支持的安卓动画交换包')
    cid=package.get('characterId')
    if not cid: raise ValueError('缺少 characterId')
    root=resolve(cid)
    if not cmds.attributeQuery('integratedRigData',node=root,exists=True): raise ValueError('非本套绑定')
    meta=json.loads(cmds.getAttr(root+'.integratedRigData'))
    if str(meta.get('version'))!=str(package.get('rigVersion')): raise ValueError('绑定版本不匹配')
    registered=set()
    for part in meta.get('parts',{}).values():
        for field in ('controls','zero_controls'):
            for node in part.get(field,{}).values():
                if cmds.objExists(node): registered.update(cmds.ls(node,long=True) or [])
    if meta.get('master_control'):registered.add(resolve(cmds.ls(meta['master_control'],uuid=True)[0]))
    for item in meta.get('generic_objects',[]):
        if item.get('control_uuid'):registered.add(resolve(item['control_uuid']))
    # Reconstruct the allowed private input table from this live character,
    # never trust arbitrary destination plugs supplied in a phone file.
    import runpy
    dynamic={'rigMetadata':meta,'controls':[]}
    runpy.run_path(str(Path(__file__).with_name('export_modes.py')))['extend_snapshot'](dynamic)
    bindings={r['id']:r for r in dynamic['controls']}
    mode_ids={r['id'] for r in dynamic.get('modePanel',{}).values()}
    step_ids=set(mode_ids)
    for role,cfg in dynamic.get('modePanel',{}).items():
        if role.startswith('generic_'):step_ids.update(cfg['offsetIds'])
    for row in bindings.values():registered.add(resolve(row['nodeId']))
    fps=package.get('fps');time_scale=1.0
    if fps is not None:
        unit=cmds.currentUnit(q=True,time=True)
        current={'film':24,'pal':25,'ntsc':30,'show':48,'palf':50,'ntscf':60}.get(unit)
        if current is None and unit.endswith('fps'): current=float(unit[:-3])
        if current is None or number(fps)<=0: raise ValueError('不支持的帧率')
        # Preserve duration in seconds without changing the user's Maya time unit.
        time_scale=current/number(fps)
    mode=package.get('valueSpace','local-absolute');base={};snapshot=None
    if mode=='snapshot-local-delta':
        if not snapshot_path: raise ValueError('增量动画必须提供原始 snapshot_path')
        raw=Path(snapshot_path).read_bytes()
        snapshot=json.loads(raw.decode('utf-8-sig'))
        if snapshot.get('format')=='maya-mobile-project':
            raw=snapshot['snapshotJson'].encode('utf-8')
            snapshot=json.loads(raw.decode('utf-8-sig'))
        if hashlib.sha256(raw).hexdigest()!=package.get('sourceSnapshotSha256'): raise ValueError('源快照 SHA256 不匹配')
        if snapshot.get('characterId')!=cid or snapshot.get('rigVersion')!=package.get('rigVersion'): raise ValueError('源工程身份不匹配')
        base={c['id']:{a:number(c['channels'][a]['value']) for a in ATTRS if a in c.get('channels',{})} for c in snapshot['controls']}
    elif mode!='local-absolute': raise ValueError('未知通道坐标模式')
    interpolation=package.get('interpolation','linear')
    if interpolation not in ('linear','maya-auto-ease'): raise ValueError('不支持的动画插值')
    smooth=package.get('autoEaseControls',[])
    if not isinstance(smooth,list) or any(not isinstance(uid,str) for uid in smooth): raise ValueError('无效曲线控制器列表')
    smooth=set(smooth) if interpolation=='maya-auto-ease' else set()
    policy=package.get('curvePolicy','merge')
    if policy not in ('merge','replace-auto-ease-tracks'): raise ValueError('不支持的曲线导入策略')
    curve_io=runpy.run_path(str(Path(__file__).with_name('animation_curves.py')))
    import_rows,source_specs,static_channels=curve_io['prepare'](package,base)
    tangent_modes={};replace_plugs=set();original_plugs={};static_plugs={}
    resolved={};operations=[];seen=set()
    for row in import_rows:
        frame=number(row['frame'])*time_scale
        for uid,pose in row.get('values',{}).items():
            if (uid,frame) in seen: raise ValueError('同一控制器关键帧重复')
            seen.add((uid,frame));node=resolved.setdefault(uid,resolve(bindings[uid]['nodeId'] if uid in bindings else uid))
            source_animation=bindings.get(uid,{}).get('sourceAnimation',False)
            if node not in registered or (not node.startswith(root+'|') and not source_animation): raise ValueError('控制器不属于该角色登记表: '+uid)
            attributes={}
            if not isinstance(pose,dict): channels={'rotateY':number(pose)}
            else:
                channels={a:number(pose[a]) for a in ATTRS if a in pose}
                if 'translate' in pose:
                    if any(a in pose for a in ATTRS[3:]): raise ValueError('平移通道不能同时使用数组和独立属性')
                    tr=pose['translate']
                    if not isinstance(tr,list) or len(tr)!=3: raise ValueError('translate 必须为三分量')
                    channels.update({a:number(v) for a,v in zip(ATTRS[3:],tr)})
                raw_attributes=pose.get('attributes',{})
                if raw_attributes is not None:
                    if not isinstance(raw_attributes,dict): raise ValueError('attributes 必须为对象')
                    for attr,value in raw_attributes.items():
                        if not isinstance(attr,str) or not ATTR_NAME.match(attr): raise ValueError('非法绑定属性名: '+str(attr))
                        if attr in ATTRS: raise ValueError('绑定属性不能覆盖 TR 通道: '+attr)
                        if not cmds.attributeQuery(attr,node=node,exists=True): raise ValueError('控制器缺少绑定属性: '+uid+'.'+attr)
                        attributes[attr]=number(value)
            if not channels: raise ValueError('空姿态')
            for attr,value in channels.items():
                if mode=='snapshot-local-delta':
                    if attr not in base.get(uid,{}): raise ValueError('快照缺少基准通道: '+uid+'.'+attr)
                    value+=base[uid][attr]
                plug=bindings[uid]['inputPlugs'][ATTRS.index(attr)] if uid in bindings else node+'.'+attr
                if not plug:raise ValueError('未登记的内部输入通道: '+uid+'.'+attr)
                if uid in mode_ids and value not in (0,1):raise ValueError('模式关键帧必须为 0 或 1')
                if cmds.getAttr(plug,lock=True) or cmds.referenceQuery(node,isNodeReferenced=True): raise ValueError('锁定通道或引用节点: '+plug)
                drivers=cmds.listConnections(plug,source=True,destination=False) or []
                if any(cmds.nodeType(n) not in ('animCurveTA','animCurveTL','animCurveTU') for n in drivers): raise ValueError('约束、动画层或其他驱动通道: '+plug)
                operations.append((plug,frame,value));tangent_modes[plug]='step' if uid in step_ids else 'autoease' if uid in smooth else 'linear'
                if uid in smooth:replace_plugs.add(plug)
                if (uid,attr) in source_specs:original_plugs[plug]=source_specs[uid,attr]
                if (uid,attr) in static_channels:static_plugs[plug]=value
            for attr,value in attributes.items():
                plug=driven_attribute_target(node,attr)
                if cmds.getAttr(plug,lock=True) or cmds.referenceQuery(node,isNodeReferenced=True): raise ValueError('锁定通道或引用节点: '+plug)
                drivers=cmds.listConnections(plug,source=True,destination=False) or []
                if any(cmds.nodeType(n) not in ('animCurveTA','animCurveTL','animCurveTU','animCurveUU','animCurveUL','animCurveUA') for n in drivers): raise ValueError('约束、动画层或其他驱动通道: '+plug)
                operations.append((plug,frame,value));tangent_modes[plug]='autoease' if uid in smooth else 'linear'
    camera_curves,camera_count=runpy.run_path(str(Path(__file__).with_name('camera_animation.py')))['prepare'](package,snapshot,time_scale)
    for plug,data in camera_curves.items():
        if plug in tangent_modes:raise ValueError('相机和绑定输入引用同一通道，不能重复写入：'+plug)
        original_plugs[plug]=data;tangent_modes[plug]='linear'
        if data['times']:
            operations.extend((plug,number(t)*time_scale,number(v)) for t,v in zip(data['times'],data['values']))
        else:
            static_plugs[plug]=number(data['staticValue']);operations.append((plug,number(package.get('frame',0))*time_scale,number(data['staticValue'])))
    if not operations and not camera_count: raise ValueError('没有可导入关键帧')
    result={'characterId':cid,'rigVersion':package['rigVersion'],'keys':len(seen),'channelKeys':sum(plug not in static_plugs for plug,_,_ in operations),'controls':sorted(resolved.values()),'dryRun':bool(dry_run),'valueSpace':mode,'interpolation':interpolation,'timeScale':time_scale,'curvePolicy':policy,'originalCurveTracks':len(original_plugs),'staticChannels':len(static_plugs),'legacySampledImport':package.get('curvePayloadVersion')!=1 and bool(package.get('sampling'))}
    result['cameras']=camera_count;result['cameraCurveTracks']=len(camera_curves);result['cameraChannelKeys']=sum(len(d['times']) for d in camera_curves.values())
    if dry_run or not operations: return result
    if not cmds.undoInfo(q=True,state=True): raise RuntimeError('撤销关闭，无法安全回滚')
    backup={'scene':cmds.file(q=True,sn=True),'package':str(path),'channels':{}}
    for plug in sorted({op[0] for op in operations}):
        data={'value':cmds.getAttr(plug),'times':cmds.keyframe(plug,q=True,tc=True) or [],'values':cmds.keyframe(plug,q=True,vc=True) or []}
        for flag in ('inTangentType','outTangentType','inAngle','outAngle','inWeight','outWeight','weightedTangents','lock','weightLock'):
            data[flag]=cmds.keyTangent(plug,q=True,**{flag:True}) or []
        data['breakdownTimes']=cmds.keyframe(plug,q=True,breakdown=True,tc=True) or []
        drivers=cmds.listConnections(plug,source=True,destination=False,type='animCurve') or []
        if drivers:
            for field in ('preInfinity','postInfinity','rotationInterpolation'):
                if cmds.attributeQuery(field,node=drivers[0],exists=True):data[field]=cmds.getAttr(drivers[0]+'.'+field)
        backup['channels'][plug]=data
    folder=Path(backup_directory) if backup_directory else Path(path).parent/'maya-animation-backups';folder.mkdir(parents=True,exist_ok=True)
    backup_path=folder/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
    backup_path.write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding='utf-8')
    before_time=cmds.currentTime(q=True);before_selection=cmds.ls(sl=True,long=True) or [];before_modified=cmds.file(q=True,modified=True)
    started=False
    from maya_agent.rigs import arm_ik
    previous_busy=arm_ik._busy;arm_ik._busy=True
    cmds.undoInfo(openChunk=True,chunkName='MayaMobileAnimationImport')
    try:
        for plug in set(original_plugs)|set(static_plugs):
            started=True;cmds.cutKey(plug,clear=True)
        # A mobile-authored curve is a complete track. Retaining hidden old Maya keys
        # would change Auto Ease slopes. The full original curves are backed up above.
        if policy=='replace-auto-ease-tracks':
            for plug,tangent in tangent_modes.items():
                if tangent=='autoease' or plug in replace_plugs:
                    started=True;cmds.cutKey(plug,clear=True)
                    if cmds.listConnections(plug,source=True,destination=False,type='animCurve'):
                        cmds.keyTangent(plug,weightedTangents=False)
        for plug,frame,value in operations:
            if plug in static_plugs:continue
            started=True;cmds.setKeyframe(plug,time=frame,value=value,inTangentType='linear' if tangent_modes[plug]=='step' else tangent_modes[plug],outTangentType=tangent_modes[plug])
        for plug,value in static_plugs.items():
            started=True;cmds.setAttr(plug,value)
        for plug,data in original_plugs.items():curve_io['restore_tangents'](plug,data,time_scale)
    except Exception:
        cmds.undoInfo(closeChunk=True)
        if started: cmds.undo()
        cmds.currentTime(before_time)
        if before_selection: cmds.select(before_selection,replace=True)
        else: cmds.select(clear=True)
        cmds.file(modified=before_modified)
        raise
    else: cmds.undoInfo(closeChunk=True)
    finally:arm_ik._busy=previous_busy;arm_ik._sync_mode_cache()
    result['backup']=str(backup_path)
    return result
