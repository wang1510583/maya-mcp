"""Variable-length FK finger chains, discovered from the source DAG."""
import math

VERSION = '1.0.0'


def character_for(parts):
    """Find an existing character by its actual driven wrist, not its name."""
    import json
    import maya.cmds as c
    wrists={c.ls(inspect_selection(opt['targets'])['wrist'],uuid=True)[0] for opt in parts.values()}
    found=[]
    for root in c.ls('*.integratedRigData','*:*.integratedRigData',o=True) or []:
        rig=json.loads(c.getAttr(root+'.integratedRigData'))
        targets={c.ls(m['target'],uuid=True)[0] for p in rig['parts'].values()
                 for m in p.get('original_target_mapping',[]) if c.objExists(m['target'])}
        if wrists.issubset(targets):found.append(root)
    return found[0] if len(found)==1 else None


def append(character,parts):
    """Add only missing hands to an existing rig; never rebuild its limbs."""
    import json
    import maya.cmds as c
    from maya_agent.rigs.integrated import VERSION as integrated_version
    from maya_agent.rigs.integrated.builder import build as create
    rig=json.loads(c.getAttr(character+'.integratedRigData'))
    if set(parts)-{'hand_L','hand_R'} or not parts:raise ValueError('追加手指只接受左手或右手。')
    if set(parts)&set(rig['parts']):raise ValueError('此角色已创建对应手指，请勿重复创建。')
    if c.referenceQuery(character,isNodeReferenced=True) or any(c.lockNode(character,q=True,lock=True)):
        raise ValueError('角色属于引用或已锁定。')
    found=character_for(parts)
    if not found or c.ls(found,l=True)!=c.ls(character,l=True):raise ValueError('手指的手腕不属于此角色。')
    c.undoInfo(openChunk=True,chunkName='AppendCharacterFingers')
    try:
        addition=create(parts,namespace=rig['namespace']+'_fingers',zero_controls=True,create_master=False)
        # This remains an owned support group, not a second independent character.
        c.parent(addition['root'],character,relative=True)
        c.setAttr(addition['root']+'.integratedRigData',lock=False);c.deleteAttr(addition['root']+'.integratedRigData')
        rig['parts'].update(addition['parts']);rig['version']=integrated_version
        rig.setdefault('finger_additions',[]).append(addition['root'])
        rig.setdefault('original_animation_backups',[]).extend(addition['original_animation_backups'])
        rig['skipped']=[k for k in rig.get('skipped',[]) if k not in parts]
        c.setAttr(character+'.integratedRigData',lock=False)
        c.setAttr(character+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
        return rig
    finally:c.undoInfo(closeChunk=True)


def chains_from_parents(names, parents):
    if not names or len(set(names)) != len(names):
        raise ValueError('请载入不重复的手指骨骼。')
    selected = set(names)
    roots = [n for n in names if parents[n] not in selected]
    if not roots or len({parents[n] for n in roots}) != 1 or parents[roots[0]] is None:
        raise ValueError('所有手指第一节必须连接同一个手腕；不能漏选中间关节或混选两只手。')
    children = {n: [v for v in names if parents[v] == n] for n in names}
    if any(len(v) > 1 for v in children.values()):
        raise ValueError('单根手指内不能分叉；请从手腕下的各根手指开始选择。')
    chains = []
    for root in roots:
        chain = []; node = root
        while node:
            if node in chain:raise ValueError('手指层级存在循环。')
            chain.append(node); node = next(iter(children[node]), None)
        chains.append(chain)
    if sum(map(len, chains)) != len(names):raise ValueError('存在不连续或循环的手指层级。')
    return chains, parents[roots[0]]


def inspect_selection(names):
    import maya.cmds as c
    nodes = []
    for name in names:
        found = c.ls(name, long=True) or []
        if len(found) != 1 or c.nodeType(found[0]) != 'joint':raise ValueError('手指只能载入唯一的骨骼。')
        nodes.append(found[0])
    parents = {n: (c.listRelatives(n, p=True, f=True) or [None])[0] for n in nodes}
    chains, wrist = chains_from_parents(nodes, parents)
    return dict(chains=[[nodes.index(n) for n in chain] for chain in chains], wrist=wrist)


def build(item, targets, namespace, side):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    c.namespace(add=namespace)
    root = c.createNode('transform', name=namespace+':rig_root')
    c.setAttr(root+'.inheritsTransform', False)
    c.connectAttr(item['topology']['wrist']+'.worldMatrix[0]', root+'.offsetParentMatrix')
    current = c.currentTime(q=True); controls = {}; mappings = []
    def pose(frame, index):
        p = item['motion'][frame][index]; m = list(p['rotation']); m[12:15] = p['pivot']
        return om.MMatrix(m)
    for finger, chain in enumerate(item['topology']['chains'], 1):
        parent = root; previous_index = None
        for segment, index in enumerate(chain, 1):
            role = 'finger%02d_%02d' % (finger, segment)
            parent_rest = pose(current, previous_index) if previous_index is not None else om.MMatrix(item['wrist_motion'][current])
            rest = pose(current, index) * parent_rest.inverse()
            zero = c.createNode('transform', name=namespace+':'+role+'_zero', parent=parent)
            c.setAttr(zero+'.offsetParentMatrix', *list(rest), type='matrix')
            points = item['motion'][current]
            neighbor = chain[segment] if segment < len(chain) else (chain[segment-2] if segment > 1 else None)
            length = math.dist(points[index]['pivot'], points[neighbor]['pivot']) if neighbor is not None else 2.0
            size = max(.15, length*.36)*item['options'].get('control_size', 1.0)
            control = c.circle(name=namespace+':'+role+'_'+side, normal=(1,0,0), radius=size, ch=False)[0]
            c.parent(control, zero, relative=True); controls[role] = control
            for a in ('sx','sy','sz','v'):c.setAttr(control+'.'+a, lock=True, keyable=False)
            for shape in c.listRelatives(control,s=True,f=True):
                c.setAttr(shape+'.overrideEnabled',True); c.setAttr(shape+'.overrideColor',6 if side=='L' else 13)
            previous_euler = None
            if item['frames']:
                for frame in sorted(item['motion']):
                    parent_pose = pose(frame, previous_index) if previous_index is not None else om.MMatrix(item['wrist_motion'][frame])
                    local = pose(frame,index)*parent_pose.inverse()*rest.inverse()
                    tm = om.MTransformationMatrix(local); rotation = tm.rotation(asQuaternion=True).asEulerRotation()
                    if previous_euler is not None:rotation = rotation.closestSolution(previous_euler)
                    previous_euler = rotation
                    values = list(tm.translation(om.MSpace.kTransform))+[math.degrees(v) for v in rotation]
                    for attr,value in zip(('tx','ty','tz','rx','ry','rz'),values):
                        c.setKeyframe(control,at=attr,t=frame,v=value,itt='linear',ott='linear')
            target = targets[index]
            for attr in ('tx','ty','tz','rx','ry','rz'):
                incoming = c.connectionInfo(target+'.'+attr,sfd=True)
                if incoming:c.disconnectAttr(incoming,target+'.'+attr)
            constraint = c.parentConstraint(control,target,mo=False)[0]
            mappings.append(dict(target=target,driver=control,constraint=constraint))
            parent = control; previous_index = index
    c.currentTime(current)
    return dict(root=root,namespace=namespace,version=VERSION,side=side,controls=controls,
                zero_controls=controls.copy(),native_zero=True,follows_wrist=True,wrist=item['topology']['wrist'],
                chains=item['topology']['chains'],target_mapping=mappings,joints=[],nodes=c.ls(namespace+':*'))
