"""Uniform character scale, propagated once into the original skeleton DAG.

The existing master matrix scales the solver/input containers. Parent constraints
carry their positions and rotations to original targets but omit scale. A uniform
OPM factor on each topmost driven target supplies that missing inherited scale,
without replacing joint scale curves or triggering segmentScaleCompensate.
"""
from maya_agent.rigs import scene_data
import json
import re

VERSION='1.1.0'
ATTRIBUTE='characterMasterScaleData'


def repair_legacy_skin_frames(nodes, root=None):
    """Migrate only the known v1 skin wrappers; keep weights and the solve intact.

    Old unused wrappers are retained for recovery. This also handles wrappers
    whose character root was deleted: their stored inverse may be constant.
    """
    import maya.cmds as c
    rows=[];original_edges=[];created=[]
    marker=root+'.'+ATTRIBUTE if root else None
    old_text=c.getAttr(marker) if marker else None
    for node in nodes:
        if c.nodeType(node)!='multMatrix' or not re.fullmatch(r'masterSkinFrame\d+',node.rsplit(':',1)[-1]):
            raise ValueError('不是已登记的旧蒙皮缩放节点：'+node)
        indices=set(c.getAttr(node+'.matrixIn',multiIndices=True) or [])
        if 0 not in indices or indices-{0,1}:
            raise ValueError('旧蒙皮缩放结构已修改：'+node)
        influence=c.connectionInfo(node+'.matrixIn[0]',sfd=True)
        if not re.search(r'\.worldMatrix\[\d+\]$',influence) or not c.objectType(influence.split('.')[0],isAType='transform'):
            raise ValueError('旧蒙皮节点没有原骨骼输入：'+node)
        for dst in c.listConnections(node+'.matrixSum',s=False,d=True,p=True) or []:
            match=re.fullmatch(r'(.+)\.matrix\[(\d+)\]',dst)
            if not match or c.nodeType(match[1])!='skinCluster':
                raise ValueError('旧蒙皮节点存在未知输出：'+dst)
            bind=match[1]+'.bindPreMatrix['+match[2]+']'
            if any(c.getAttr(p,lock=True) for p in (dst,bind)) or c.referenceQuery(match[1],isNodeReferenced=True):
                raise ValueError('不能修复引用或锁定蒙皮：'+dst)
            rows.append(dict(destination=bind,source=c.connectionInfo(bind,sfd=True),value=c.getAttr(bind),influence=influence,legacy=node,matrix_destination=dst))
    c.undoInfo(openChunk=True,chunkName='RepairCharacterSkinInfluences')
    try:
        for row in rows:
            node=c.createNode('multMatrix',name=row['legacy'].rsplit(':',1)[0]+':masterSkinBindRepair');created.append(node)
            if row['source']:c.connectAttr(row['source'],node+'.matrixIn[0]')
            else:c.setAttr(node+'.matrixIn[0]',*row['value'],type='matrix')
            c.connectAttr(row['influence'],node+'.matrixIn[1]')
            correction=row['legacy']+'.matrixIn[1]';source=c.connectionInfo(correction,sfd=True)
            if source:c.connectAttr(source,node+'.matrixIn[2]')
            else:c.setAttr(node+'.matrixIn[2]',*c.getAttr(correction),type='matrix')
            c.connectAttr(row['influence'].replace('.worldMatrix[','.worldInverseMatrix['),node+'.matrixIn[3]')
            row['matrix']=node
            original_edges.append((row['destination'],row['source'],row['value']))
            c.connectAttr(node+'.matrixSum',row['destination'],force=True)
            original_edges.append((row['matrix_destination'],row['legacy']+'.matrixSum',None))
            c.connectAttr(row['influence'],row['matrix_destination'],force=True)
        if marker:
            data=json.loads(old_text);data['version']=VERSION;data['skin_inputs']=rows;data['created']+=created
            c.setAttr(marker,lock=False);c.setAttr(marker,json.dumps(data),type='string',lock=True)
        return rows
    except Exception:
        for dst,src,value in reversed(original_edges):
            current=c.connectionInfo(dst,sfd=True)
            if current:c.disconnectAttr(current,dst)
            if src:c.connectAttr(src,dst)
            else:c.setAttr(dst,*value,type='matrix')
        if marker:
            c.setAttr(marker,lock=False);c.setAttr(marker,old_text,type='string',lock=True)
        for node in reversed(created):
            if c.objExists(node):c.delete(node)
        raise
    finally:c.undoInfo(closeChunk=True)

def inherits_scale(node, roots):
    import maya.cmds as c
    node=c.ls(node,long=True)[0]
    while node:
        if node in roots:return True
        if not c.getAttr(node+'.inheritsTransform'):return False
        node=(c.listRelatives(node,parent=True,fullPath=True) or [None])[0]
    return False

def rollback(rig):
    """Release original skeleton/skin inputs before a failed assembly is deleted."""
    import maya.cmds as c
    root=rig['root'];marker=root+'.'+ATTRIBUTE
    if not c.objExists(marker):return
    data=scene_data.read(marker);plug=data['attribute']
    for row in reversed(data['targets']+data.get('skin_inputs',[])):
        dst=row['destination'];source=c.connectionInfo(dst,sfd=True)
        if source:c.disconnectAttr(source,dst)
        if row['source']:c.connectAttr(row['source'],dst)
        else:c.setAttr(dst,*row['value'],type='matrix')
    for a in 'XYZ':
        axis=data['control']+'.scale'+a;c.setAttr(axis,lock=False)
        if c.connectionInfo(axis,sfd=True)==plug:c.disconnectAttr(plug,axis)
        c.setAttr(axis,1);c.setAttr(axis,lock=True,keyable=False,channelBox=False)
    c.setAttr(marker,lock=False);c.deleteAttr(marker)
    for node in reversed(data['created']):
        if c.objExists(node):c.delete(node)
    c.deleteAttr(plug);rig.pop('overall_scale',None)


def enable(rig):
    import maya.cmds as c
    root=rig['root'];control=rig['master_control'];plug=control+'.overallScale'
    if c.objExists(root+'.'+ATTRIBUTE):
        data=scene_data.read(root+'.'+ATTRIBUTE)
        if data['control']!=control or not c.objExists(plug):
            raise ValueError('整体缩放登记已损坏，请恢复原节点。')
        if data['version']=='1.0.0':
            repair_legacy_skin_frames(list(dict.fromkeys(row['matrix'] for row in data.get('skin_inputs',[]))),root)
            data=scene_data.read(root+'.'+ATTRIBUTE)
        rig['overall_scale']=plug
        return data
    if c.objExists(plug):raise ValueError('总圆环已有同名 overallScale 属性，请先核对。')
    axes=[control+'.scale'+a for a in 'XYZ']
    for axis in axes:
        if c.connectionInfo(axis,sfd=True) or abs(c.getAttr(axis)-1)>1e-10:
            raise ValueError('安装整体缩放前，总圆环缩放必须为 1 且没有其他驱动：'+axis)
    targets=set()
    for part in rig['parts'].values():
        for row in part.get('original_target_mapping',[]):
            found=c.ls(row['target'],long=True) or []
            if len(found)!=1:raise ValueError('整体缩放目标不存在或不唯一：'+row['target'])
            targets.add(found[0])
    # Descendants inherit the OPM factor even when joint SSC is enabled. Applying
    # it to each joint would multiply the scale once per level of the skeleton.
    tops=sorted(n for n in targets if not any(n.startswith(p+'|') for p in targets if p!=n))
    rows=[]
    for node in tops:
        dst=node+'.offsetParentMatrix'
        if c.referenceQuery(node,isNodeReferenced=True) or c.getAttr(dst,lock=True) or any(c.lockNode(node,q=True,lock=True)):
            raise ValueError('不能安装整体缩放到引用或锁定骨骼：'+node)
        if not c.getAttr(node+'.inheritsTransform'):
            raise ValueError('整体缩放需要骨骼保留父级继承：'+node)
        rows.append(dict(node=node,destination=dst,source=c.connectionInfo(dst,sfd=True),value=c.getAttr(dst),kind='skeleton'))
    # A registered descendant that ignores its parent needs an independent root.
    for node in targets-set(tops):
        path=node
        while path not in tops:
            if not c.getAttr(path+'.inheritsTransform'):
                raise ValueError('骨骼链中存在关闭父级继承的节点：'+path)
            path=c.listRelatives(path,parent=True,fullPath=True)[0]
    # Keep joint.worldMatrix directly connected: Maya uses those connections to
    # discover paintable influences. Cancel only the added scale in each bind
    # matrix, then apply it once in geometry space (including animated parents).
    from .master_control import _nodes
    scaled_roots=set(tops)|set(_nodes(rig));skin_inputs=[];geometries=set()
    for skin in c.ls(type='skinCluster') or []:
        influences=c.skinCluster(skin,q=True,influence=True) or []
        if not any(inherits_scale(n,scaled_roots) for n in influences):continue
        for index in c.getAttr(skin+'.matrix',multiIndices=True) or []:
            dst='%s.matrix[%d]'%(skin,index);src=c.connectionInfo(dst,sfd=True)
            if not src:continue
            node=src.rsplit('.',1)[0]
            if not c.objectType(node,isAType='transform') or not re.search(r'\.worldMatrix\[\d+\]$',src):
                raise ValueError('蒙皮矩阵包含自定义驱动，不能直接安装整体缩放：'+dst)
            if inherits_scale(node,scaled_roots):
                dst='%s.bindPreMatrix[%d]'%(skin,index)
                if c.getAttr(dst,lock=True) or c.referenceQuery(skin,isNodeReferenced=True):raise ValueError('蒙皮缩放输入已锁定或引用：'+dst)
                skin_inputs.append(dict(destination=dst,source=c.connectionInfo(dst,sfd=True),value=c.getAttr(dst),influence=src))
        for shape in c.skinCluster(skin,q=True,geometry=True) or []:
            parents=c.listRelatives(shape,parent=True,fullPath=True) or []
            if len(parents)!=1:raise ValueError('整体缩放不支持实例蒙皮：'+shape)
            geometries.add(parents[0])
    for node in sorted(geometries,key=lambda n:(n.count('|'),n)):
        if inherits_scale(node,scaled_roots):continue
        if any(top.startswith(node+'|') for top in tops):raise ValueError('蒙皮物体是骨架祖先，需要先分离缩放空间：'+node)
        dst=node+'.offsetParentMatrix'
        if c.referenceQuery(node,isNodeReferenced=True) or c.getAttr(dst,lock=True) or any(c.lockNode(node,q=True,lock=True)):raise ValueError('蒙皮物体空间已锁定或引用：'+node)
        rows.append(dict(node=node,destination=dst,source=c.connectionInfo(dst,sfd=True),value=c.getAttr(dst),kind='geometry'))
        scaled_roots.add(node)
    before={n:c.xform(n,q=True,ws=True,m=True) for n in targets|geometries}
    created=[];replaced=[];added=False
    flags={p:dict(lock=c.getAttr(p,lock=True),keyable=c.getAttr(p,keyable=True),channelBox=c.getAttr(p,channelBox=True)) for p in axes}
    c.undoInfo(openChunk=True,chunkName='EnableCharacterUniformScale')
    try:
        c.addAttr(control,ln='overallScale',nn='整体缩放',at='double',minValue=.001,defaultValue=1,keyable=True);added=True
        for axis in axes:
            c.setAttr(axis,lock=False);c.connectAttr(plug,axis);c.setAttr(axis,lock=True,keyable=False,channelBox=False)
        scale=c.createNode('composeMatrix',name=rig['namespace']+':masterSkeletonScale');created.append(scale)
        for a in 'XYZ':c.connectAttr(plug,scale+'.inputScale'+a)
        rigid=c.createNode('pickMatrix',name=rig['namespace']+':masterRigidFrame');created.append(rigid)
        c.setAttr(rigid+'.useScale',False);c.setAttr(rigid+'.useShear',False);c.connectAttr(control+'.worldMatrix[0]',rigid+'.inputMatrix')
        inv=c.createNode('inverseMatrix',name=rig['namespace']+':masterRigidInverse');created.append(inv);c.connectAttr(rigid+'.outputMatrix',inv+'.inputMatrix')
        delta=c.createNode('multMatrix',name=rig['namespace']+':masterScaleDelta');created.append(delta)
        c.connectAttr(inv+'.outputMatrix',delta+'.matrixIn[0]');c.connectAttr(control+'.worldMatrix[0]',delta+'.matrixIn[1]')
        undo_scale=c.createNode('inverseMatrix',name=rig['namespace']+':masterScaleInverse');created.append(undo_scale);c.connectAttr(delta+'.matrixSum',undo_scale+'.inputMatrix')
        for i,row in enumerate(rows):
            matrix=c.createNode('multMatrix',name=rig['namespace']+':masterSkeletonScale%02d'%i);created.append(matrix)
            if row['source']:c.connectAttr(row['source'],matrix+'.matrixIn[0]')
            else:c.setAttr(matrix+'.matrixIn[0]',*row['value'],type='matrix')
            if row['kind']=='skeleton':c.connectAttr(scale+'.outputMatrix',matrix+'.matrixIn[1]')
            else:
                parent=(c.listRelatives(row['node'],parent=True,fullPath=True) or [None])[0]
                if parent and c.getAttr(row['node']+'.inheritsTransform'):
                    c.connectAttr(parent+'.worldMatrix[0]',matrix+'.matrixIn[1]');c.connectAttr(delta+'.matrixSum',matrix+'.matrixIn[2]');c.connectAttr(parent+'.worldInverseMatrix[0]',matrix+'.matrixIn[3]')
                else:c.connectAttr(delta+'.matrixSum',matrix+'.matrixIn[1]')
            row['matrix']=matrix
            replaced.append(row);c.connectAttr(matrix+'.matrixSum',row['destination'],force=True)
        for i,row in enumerate(skin_inputs):
            matrix=c.createNode('multMatrix',name=rig['namespace']+':masterSkinBind%02d'%i);created.append(matrix)
            if row['source']:c.connectAttr(row['source'],matrix+'.matrixIn[0]')
            else:c.setAttr(matrix+'.matrixIn[0]',*row['value'],type='matrix')
            # B' * J = B * J * inverse(delta). Keep J connected to skin.matrix.
            c.connectAttr(row['influence'],matrix+'.matrixIn[1]')
            c.connectAttr(undo_scale+'.outputMatrix',matrix+'.matrixIn[2]')
            c.connectAttr(row['influence'].replace('.worldMatrix[','.worldInverseMatrix['),matrix+'.matrixIn[3]');row['matrix']=matrix
            replaced.append(row);c.connectAttr(matrix+'.matrixSum',row['destination'],force=True)
        error=max([abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))] or [0])
        if error>1e-5:raise RuntimeError('安装整体缩放改变了原姿态：'+str(error))
        data=dict(version=VERSION,control=control,attribute=plug,created=created,targets=rows,skin_inputs=skin_inputs)
        c.addAttr(root,ln=ATTRIBUTE,dt='string');c.setAttr(root+'.'+ATTRIBUTE,json.dumps(data),type='string',lock=True)
        rig['overall_scale']=plug
        return data
    except Exception:
        for row in reversed(replaced):
            source=c.connectionInfo(row['destination'],sfd=True)
            if source:c.disconnectAttr(source,row['destination'])
            if row['source']:c.connectAttr(row['source'],row['destination'])
            else:c.setAttr(row['destination'],*row['value'],type='matrix')
        for axis in axes:
            c.setAttr(axis,lock=False)
            if c.connectionInfo(axis,sfd=True)==plug:c.disconnectAttr(plug,axis)
            c.setAttr(axis,1);c.setAttr(axis,**flags[axis])
        if c.objExists(root+'.'+ATTRIBUTE):c.setAttr(root+'.'+ATTRIBUTE,lock=False);c.deleteAttr(root+'.'+ATTRIBUTE)
        for node in reversed(created):
            if c.objExists(node):c.delete(node)
        if added:c.deleteAttr(plug)
        raise
    finally:c.undoInfo(closeChunk=True)
