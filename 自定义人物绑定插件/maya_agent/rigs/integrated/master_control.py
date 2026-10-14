"""An origin-centered character offset, including independent IK inputs.

Apply the same world delta to part containers and independent input spaces.
Frozen animation references and solver outputs are never patched or re-keyed.
"""
import json
import math

VERSION = '1.0.0'
ATTRIBUTE = 'characterMasterData'


def _nodes(rig):
    import maya.cmds as c
    result = [p['root'] for p in rig['parts'].values()]
    external = rig.get('general_root')
    if not external and rig.get('space_root'):
        result.append(rig['space_root'])
    elif external:
        # External roots belong to the user. Move only our alternate-space
        # targets under them, never the external node or its animation.
        external = c.ls(external, long=True)[0]
        for space in rig.get('spaces', []):
            if c.ls(space['driver'], long=True) != [external]:
                continue
            constraint = space['constraint']
            query = c.orientConstraint if space.get('orientation_only') else c.parentConstraint
            targets = query(constraint, q=True, targetList=True)
            if len(targets) != 2:
                raise ValueError('总控制器需要原有的双目标空间：' + constraint)
            result.append(targets[1])
    return list(dict.fromkeys(c.ls(n, long=True)[0] for n in result))


def _radius(rig):
    import maya.cmds as c
    points = []
    for part in rig['parts'].values():
        for entry in part.get('original_target_mapping', []):
            points.append(c.xform(entry['target'], q=True, ws=True, t=True))
    return max([1.0] + [math.hypot(p[0], p[2]) * 1.12 for p in points])


def attach(rig):
    """Add once to a newly built or explicitly selected existing character."""
    import maya.cmds as c
    root = rig['root']
    if c.referenceQuery(root,isNodeReferenced=True) or any(c.lockNode(root,q=True,lock=True)):
        raise ValueError('不能修改引用或锁定的角色根：'+root)
    if c.objExists(root + '.' + ATTRIBUTE):
        data = json.loads(c.getAttr(root + '.' + ATTRIBUTE))
        if not c.objExists(data['control']):
            raise ValueError('总控制圆环已被删除，请先恢复该节点。')
        rig['master_control'] = data['control']
        return data
    nodes = _nodes(rig)
    ik_inputs = []
    for part in rig['parts'].values():
        plug = part['root']+'.armWorldIKData'
        if c.objExists(plug):
            ik_inputs.extend(json.loads(c.getAttr(plug))['controls'].values())
    for node in ik_inputs:
        if c.getAttr(node+'.inheritsTransform') or c.referenceQuery(node,isNodeReferenced=True):
            raise ValueError('独立 IK 输入空间已经被修改：'+node)
    for node in nodes:
        if c.referenceQuery(node, isNodeReferenced=True) or c.getAttr(node+'.offsetParentMatrix', lock=True):
            raise ValueError('不能修改引用或锁定的绑定空间：' + node)
        # A parent outside the character must not depend on this part's output.
        if node == c.ls(root, long=True)[0]:
            raise ValueError('无效的部位总组。')
    before = {n: c.xform(n, q=True, ws=True, m=True) for n in nodes+ik_inputs}
    created, replaced, reparented = [], [], []
    auto = c.autoKeyframe(q=True, state=True)
    selection = c.ls(sl=True, long=True) or []
    c.undoInfo(openChunk=True, chunkName='AddCharacterMasterControl')
    c.autoKeyframe(state=False)
    try:
        control = c.circle(name=rig['namespace']+':master_ctrl', normal=(0,1,0),
                           radius=_radius(rig), constructionHistory=False, sections=32)[0]
        created.append(control)
        c.parent(control, root, relative=True)
        c.setAttr(control+'.inheritsTransform', False)
        for attr in ('sx','sy','sz','v'):
            c.setAttr(control+'.'+attr, lock=True, keyable=False, channelBox=False)
        for shape in c.listRelatives(control, shapes=True, fullPath=True) or []:
            c.setAttr(shape+'.overrideEnabled', True)
            c.setAttr(shape+'.overrideColor', 17)
            c.setAttr(shape+'.lineWidth', 2)
        c.addAttr(control, ln='characterMasterOwner', at='message')
        c.connectAttr(root+'.message', control+'.characterMasterOwner')
        if ik_inputs:
            group=c.createNode('transform',name=rig['namespace']+':master_ik_inputs',parent=root)
            created.append(group);c.setAttr(group+'.inheritsTransform',False)
            c.connectAttr(control+'.worldMatrix[0]',group+'.offsetParentMatrix')
            for node in ik_inputs:
                parent=(c.listRelatives(node,parent=True,fullPath=True) or [None])[0]
                reparented.append(dict(node=node,parent=parent))
                # Keep the original input OPM and every animated TR value.
                # A separate parent also leaves the native manipulation basis
                # identical to Maya's usual transform hierarchy.
                c.parent(node,group,relative=True);c.setAttr(node+'.inheritsTransform',True)
        for index,node in enumerate(nodes):
            dst = node+'.offsetParentMatrix'
            old = c.connectionInfo(dst, sourceFromDestination=True)
            value = c.getAttr(dst)
            matrix = c.createNode('multMatrix', name=rig['namespace']+':master_follow%02d'%index)
            created.append(matrix)
            if old:
                c.connectAttr(old, matrix+'.matrixIn[0]')
            else:
                c.setAttr(matrix+'.matrixIn[0]', *value, type='matrix')
            parent = (c.listRelatives(node, parent=True, fullPath=True) or [None])[0]
            if parent and c.getAttr(node+'.inheritsTransform'):
                # O' = O * P * delta * inverse(P). Do not read the driven
                # node's parentMatrix: OPM is part of that output in Maya.
                c.connectAttr(parent+'.worldMatrix[0]', matrix+'.matrixIn[1]')
                c.connectAttr(control+'.worldMatrix[0]', matrix+'.matrixIn[2]')
                c.connectAttr(parent+'.worldInverseMatrix[0]', matrix+'.matrixIn[3]')
            else:
                c.connectAttr(control+'.worldMatrix[0]', matrix+'.matrixIn[1]')
            replaced.append(dict(node=node, destination=dst, source=old, value=value, matrix=matrix))
            c.connectAttr(matrix+'.matrixSum', dst, force=True)
        error = max(abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error > 1e-5:
            raise RuntimeError('总控制圆环安装改变了原姿态：' + str(error))
        data = dict(version=VERSION, control=control, root=root, created=created, spaces=replaced,ik_inputs=reparented)
        c.addAttr(root, ln=ATTRIBUTE, dt='string')
        c.setAttr(root+'.'+ATTRIBUTE, json.dumps(data), type='string', lock=True)
        rig['master_control'] = control
        return data
    except Exception:
        for row in reversed(reparented):
            c.setAttr(row['node']+'.inheritsTransform',False)
            if row['parent']:c.parent(row['node'],row['parent'],relative=True)
            else:c.parent(row['node'],world=True,relative=True)
        for row in reversed(replaced):
            dst = row['destination']
            source = c.connectionInfo(dst, sourceFromDestination=True)
            if source: c.disconnectAttr(source,dst)
            if row['source']: c.connectAttr(row['source'],dst)
            else: c.setAttr(dst,*row['value'],type='matrix')
        if c.objExists(root+'.'+ATTRIBUTE):
            c.setAttr(root+'.'+ATTRIBUTE,lock=False);c.deleteAttr(root+'.'+ATTRIBUTE)
        for node in reversed(created):
            if c.objExists(node): c.delete(node)
        raise
    finally:
        c.autoKeyframe(state=auto)
        c.select(selection,replace=True) if selection else c.select(clear=True)
        c.undoInfo(closeChunk=True)


def upgrade(root):
    import maya.cmds as c
    rig = json.loads(c.getAttr(root+'.integratedRigData'))
    c.undoInfo(openChunk=True,chunkName='UpgradeCharacterMasterControl')
    try:
        data = attach(rig)
        c.setAttr(root+'.integratedRigData',lock=False)
        c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
        return data
    finally:
        c.undoInfo(closeChunk=True)


def upgrade_selected():
    import maya.cmds as c
    roots = [n for n in c.ls(type='transform',long=True) or []
             if c.attributeQuery('integratedRigData',node=n,exists=True)]
    selected = c.ls(sl=True,long=True) or []
    matches = []
    for root in roots:
        rig=json.loads(c.getAttr(root+'.integratedRigData'))
        containers=[root]+[p['root'] for p in rig.get('parts',{}).values()]
        paths=[c.ls(n,long=True)[0] for n in containers if c.objExists(n)]
        if any(n==p or n.startswith(p+'|') for n in selected for p in paths):
            matches.append(root)
    if len(matches)==1: root=matches[0]
    elif len(roots)==1: root=roots[0]
    else: raise ValueError('请先选择需要添加总控制圆环的角色控制器。')
    data=upgrade(root);c.select(data['control'],replace=True)
    return data
