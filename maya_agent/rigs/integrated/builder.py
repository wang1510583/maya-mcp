"""Capture all inputs before building, then attach parts and drive originals atomically."""
import json
import math
import re
from types import SimpleNamespace
from . import PARTS,VERSION


def preflight(parts):
    import maya.cmds as c
    from maya_agent.rigs.custom_body.targets import inspect
    from maya_agent.rigs.custom_body.animation import frame_range
    if not isinstance(parts,dict) or set(parts)-set(PARTS):raise ValueError('部位配置无效。')
    data={};seen=set()
    for key,options in parts.items():
        if not options.get('targets'):continue
        names=options['targets'];part=PARTS[key]
        if part['count'] and len(names)!=part['count']:
            raise ValueError('{}需要 {} 个有序目标。'.format(part['label'],part['count']))
        copy=bool(options.get('copy_animation',False))
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',options.get('name',key)):
            raise ValueError(part['label']+'的部位名称无效。')
        if copy and not options.get('drive_targets',True):raise ValueError(part['label']+'拷贝动画需要启用驱动目标。')
        if part['kind'] in ('shoulder','head'):
            size=options.get('control_size',1.0)
            if not isinstance(size,(int,float)) or not math.isfinite(size) or size<=0:raise ValueError(part['label']+'控制器大小必须大于零。')
        samples,_=inspect(names,allow_animation=copy,minimum_count=1 if part['kind']=='shoulder' else 2,
                          allow_parent_drivers=True)
        for sample in samples:
            if sample['node'] in seen:raise ValueError('同一目标不能载入多个部位：'+sample['node'])
            seen.add(sample['node'])
        frames=frame_range(options.get('start_frame',c.playbackOptions(q=True,minTime=True)),
                           options.get('end_frame',c.playbackOptions(q=True,maxTime=True)),options.get('sample_step',1)) if copy else []
        data[key]=dict(options=options,samples=samples,frames=frames,motion={})
    if not data:raise ValueError('请先左键点击部位按钮，载入所选物体。')
    return data


def capture(data,general_root=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    current=c.currentTime(q=True)
    # All samples are collected while original skeletons and curves are untouched.
    frames=sorted({current}|{f for item in data.values() for f in item['frames']})
    root_motion={}
    try:
        for frame in frames:
            c.currentTime(frame)
            if general_root:root_motion[frame]=c.xform(general_root,q=True,ws=True,m=True)
            for item in data.values():
                if frame!=current and frame not in item['frames']:continue
                poses=[]
                for sample in item['samples']:
                    matrix=c.xform(sample['node'],q=True,ws=True,m=True)
                    tm=om.MTransformationMatrix(om.MMatrix(matrix));scale=tm.scale(om.MSpace.kWorld)
                    if min(scale)<=0 or max(scale)-min(scale)>1e-5 or max(abs(v) for v in tm.shear(om.MSpace.kWorld))>1e-5:
                        raise ValueError('动画存在非均匀/负缩放或剪切：'+sample['node'])
                    poses.append(dict(matrix=matrix,rotation=list(tm.rotation(asQuaternion=True).asMatrix()),
                                      pivot=c.xform(sample['node'],q=True,ws=True,rp=True)))
                item['motion'][frame]=poses
    finally:c.currentTime(current)
    return root_motion


def root_reference(namespace,parent,motion,animated,name='general_root_reference'):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    node=c.createNode('transform',name=namespace+':'+name,parent=parent)
    c.setAttr(node+'.visibility',False)
    previous=None
    for frame,matrix in sorted(motion.items()):
        tm=om.MTransformationMatrix(om.MMatrix(matrix));rotation=tm.rotation(asQuaternion=True).asEulerRotation()
        if previous is not None:rotation=rotation.closestSolution(previous)
        previous=rotation
        scale=tm.scale(om.MSpace.kWorld)
        if min(scale)<=0 or max(scale)-min(scale)>1e-5 or max(abs(v) for v in tm.shear(om.MSpace.kWorld))>1e-5:
            raise ValueError('通用根控制器存在非均匀/负缩放或剪切。')
        values=matrix[12:15]+[math.degrees(v) for v in rotation]+list(scale)
        for attr,value in zip([p+a for p in ('translate','rotate','scale') for a in 'XYZ'],values):
            if animated:c.setKeyframe(node,at=attr,t=frame,v=value,itt='linear',ott='linear')
            else:c.setAttr(node+'.'+attr,value)
    c.dgdirty(node)
    return node


def proxies(item,namespace,group,key):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    current=c.currentTime(q=True);nodes=[]
    for i,pose in enumerate(item['motion'][current]):
        node=c.createNode('transform',name=namespace+':'+key+'_output'+str(i+1),parent=group)
        nodes.append(node)
        m=list(pose['rotation']);m[12:15]=pose['pivot'];c.xform(node,ws=True,m=m)
    if item['frames']:
        previous={}
        for f in sorted(item['motion']):
            for node,pose in zip(nodes,item['motion'][f]):
                euler=om.MTransformationMatrix(om.MMatrix(pose['rotation'])).rotation(asQuaternion=True).asEulerRotation()
                if node in previous:euler=euler.closestSolution(previous[node])
                previous[node]=euler
                values=pose['pivot']+[math.degrees(v) for v in euler]
                for a,v in zip(('translateX','translateY','translateZ','rotateX','rotateY','rotateZ'),values):
                    c.setKeyframe(node,at=a,t=f,v=v,itt='linear',ott='linear')
                c.dgdirty(node)
        c.currentTime(current)
    return nodes


def create_part(key,item,targets,namespace,chest=None):
    part=PARTS[key];opt=item['options']
    if part['kind']=='head':
        from maya_agent.rigs.head_neck import build
        return build(item,targets,namespace,chest=chest)
    if part['kind']=='shoulder':
        from .shoulder import build
        return build(item,targets,namespace,part['side'])
    kwargs=dict(targets=targets,namespace=namespace,copy_animation=bool(item['frames']))
    if item['frames']:kwargs.update(start_frame=item['frames'][0],end_frame=item['frames'][-1],sample_step=opt.get('sample_step',1))
    if part['kind']=='body':
        from maya_agent.rigs.custom_body import build
    elif part['kind']=='arm':
        from maya_agent.rigs.soft_limb import build_from_selection as build
        kwargs['side']=part['side']
    else:
        from maya_agent.rigs.soft_leg import build_from_selection as build
        kwargs['side']=part['side']
    return build(**kwargs)


def container(rig,parent,body=False):
    import maya.cmds as c
    ns=rig['namespace']+':'
    if body:
        root=c.createNode('transform',name=ns+'rig_root',parent=parent)
        tops=[n for n in c.ls(ns+'*',assemblies=True,long=True) or [] if n!=root]
        for n in tops:c.parent(n,root,relative=True)
        # The spine fitting graph originally starts with a world matrix. Normalize
        # it to the part container before evaluating the local spine chain.
        frame=c.createNode('multMatrix',name=ns+'assemblySpace')
        c.connectAttr(rig['controls']['hips']+'.worldMatrix[0]',frame+'.matrixIn[0]')
        c.connectAttr(root+'.worldInverseMatrix[0]',frame+'.matrixIn[1]')
        c.connectAttr(frame+'.matrixSum',ns+'position1.matrixIn[1]',force=True)
        rig['root']=root
    else:c.parent(rig['root'],parent,relative=True)
    return rig['root']


def build(parts,namespace='customCharacter',general_root=None):
    import maya.cmds as c
    from maya_agent.rigs.custom_body.animation import Transfer
    from maya_agent.rigs.custom_body.targets import restore
    from maya_agent.rigs.soft_leg import cleanup
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',namespace):raise ValueError('名称前缀需要英文字母、数字或下划线，不能以数字开头。')
    data=preflight(parts)
    space_root=general_root
    if general_root:
        found=c.ls(general_root,long=True) or []
        if len(found)!=1 or c.nodeType(found[0]) not in ('transform','joint'):raise ValueError('通用根控制器不存在或不是唯一的物体。')
        general_root=found[0]
        for item in data.values():
            if any(general_root==s['node'] or general_root.startswith(s['node']+'|') for s in item['samples']):
                raise ValueError('通用根不能是待创建的目标或其子级，这会产生循环。')
        space_root=general_root
    if not c.undoInfo(q=True,state=True):raise ValueError('请先开启 Maya 撤销，再执行集成创建。')
    base=namespace;i=2
    while c.namespace(exists=namespace):namespace='{}_{:02d}'.format(base,i);i+=1
    frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    selection=c.ls(sl=True,long=True) or [];old_namespace=c.namespaceInfo(currentNamespace=True)
    built={};owned=[];transfers=[];created=[];reference=None
    c.undoInfo(openChunk=True,chunkName='CreateIntegratedCharacter')
    try:
        c.autoKeyframe(state=False);root_motion=capture(data,general_root)
        c.namespace(setNamespace=':');c.namespace(add=namespace)
        root=c.createNode('transform',name=namespace+':character_rig')
        output=c.createNode('transform',name=namespace+':outputs',parent=root);c.setAttr(output+'.visibility',False)
        external_reference=root_reference(namespace,root,root_motion,any(item['frames'] for item in data.values())) if general_root else None
        for key in ['body','head','shoulder_R','shoulder_L','arm_R','arm_L','leg_R','leg_L']:
            if key not in data:continue
            item=data[key];item['proxies']=proxies(item,namespace,output,key)
            part_ns=namespace+'_'+item['options'].get('name',key)
            # Reserve ownership before calling constructors so partial failures roll back.
            if c.namespace(exists=part_ns):raise ValueError('部位名称重复或已存在：'+part_ns)
            owned.append(part_ns)
            if key=='head':
                chest=built['body']['controls']['chest'] if 'body' in built else general_root
                rig=create_part(key,item,item['proxies'],part_ns,chest=chest)
            else:rig=create_part(key,item,item['proxies'],part_ns)
            built[key]=rig
            container(rig,root,body=PARTS[key]['kind']=='body')
        # Parts never inherit another part's controls. Only an explicitly
        # loaded general root provides shared motion; old connected flags are ignored.
        for key,rig in built.items():
            rig['connected']=False
            rig['general_root_connected']=bool(general_root)
            if not general_root:continue
            group=c.createNode('transform',name=namespace+':'+key+'_attachment',parent=general_root)
            if external_reference and data[key]['frames']:
                c.connectAttr(external_reference+'.worldInverseMatrix[0]',group+'.offsetParentMatrix')
            else:
                c.setAttr(group+'.offsetParentMatrix',*c.getAttr(general_root+'.worldInverseMatrix[0]'),type='matrix')
            c.parent(rig['root'],group,relative=True)
            rig['attachment']=dict(group=group,parent=general_root)
        from .hierarchy import apply as apply_hierarchy,finish as finish_hierarchy
        hierarchy,pending=apply_hierarchy(built,data,root)
        from .spaces import apply as apply_spaces
        if not space_root:
            space_root=c.createNode('transform',name=namespace+':world_space',parent=root)
            c.setAttr(space_root+'.inheritsTransform',False);c.setAttr(space_root+'.visibility',False)
        spaces=apply_spaces(built,data,space_root)
        finish_hierarchy(built,data,root,pending)
        # Detach ALL source curves before driving any source joint. This avoids
        # interfering with children whose original parent belongs to another part.
        for key,item in data.items():
            if not item['options'].get('drive_targets',True):continue
            if item['frames']:
                transfer=Transfer(SimpleNamespace(cmds=c,namespace=namespace,created=created),item['samples'],item['frames'])
                transfers.append(transfer);transfer.detach()
        for key,item in data.items():
            if not item['options'].get('drive_targets',True):continue
            mappings=[]
            for index,(proxy,sample) in enumerate(zip(item['proxies'],item['samples'])):
                constraint=c.parentConstraint(proxy,sample['node'],maintainOffset=False,
                    name=namespace+':'+key+'_target'+str(index+1))[0]
                mappings.append(dict(target=sample['node'],driver=proxy,constraint=constraint))
            built[key]['original_target_mapping']=mappings
        # Compare originals at every requested sampling frame and static build pose.
        error=0.0
        for f in sorted({frame}|{f for item in data.values() for f in item['frames']}):
            c.currentTime(f)
            for key,item in data.items():
                if not item['options'].get('drive_targets',True):continue
                if item['frames'] and f not in item['frames']:continue
                if not item['frames'] and f!=frame:continue
                for sample,pose in zip(item['samples'],item['motion'][f]):
                    delta=max(abs(a-b) for a,b in zip(c.xform(sample['node'],q=True,ws=True,m=True),pose['matrix']))
                    error=max(error,delta)
                    if delta>1e-4:raise RuntimeError('{}动画/姿态核对失败，帧 {}，误差 {}'.format(PARTS[key]['label'],f,delta))
        result=dict(root=root,namespace=namespace,version=VERSION,parts=built,max_world_error=error,
                    skipped=[k for k in PARTS if k not in built],reference_body=reference,
                    original_animation_backups=[t.backup for t in transfers],spaces=spaces,space_root=space_root,hierarchy=hierarchy)
        result['general_root']=general_root
        from .display import apply as organize_display
        result['display']=organize_display(result)
        c.addAttr(root,ln='integratedRigData',dt='string')
        c.setAttr(root+'.integratedRigData',json.dumps(result,ensure_ascii=False),type='string',lock=True)
        return result
    except Exception:
        for t in transfers:t.release_backup()
        # Remove constraints across ALL owned parts before deleting any driver.
        for ns in owned+[namespace]:
            for n in c.ls(ns+':*',type='constraint',long=True) or []:
                if c.objExists(n):c.delete(n)
        for ns in reversed(owned):cleanup(ns)
        if c.namespace(exists=namespace):cleanup(namespace)
        for t in transfers:t.rollback()
        for item in data.values():
            if not item['frames']:restore(item['samples'])
        raise
    finally:
        try:
            c.currentTime(frame);c.autoKeyframe(state=auto);c.namespace(setNamespace=old_namespace)
            existing=[n for n in selection if c.objExists(n)]
            c.select(existing,r=True) if existing else c.select(clear=True)
        finally:c.undoInfo(closeChunk=True)
