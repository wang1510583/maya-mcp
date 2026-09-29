"""Acyclic, editable control surfaces following limb solver outputs.

Animation channels feed the original input graph. Only the independent surface's
offsetParentMatrix follows the result; its world matrix is NEVER solver input.
Playback uses the graph. Native viewport edits first rebase the input chain via
live_edit, so the manipulator uses the solved pivot and axes, not stale inputs.
"""
import json

VERSION = '1.5.1'
ROLL_ROLES = ('heel','toe_end','ball','toe')
CHANNELS = tuple(p+a for p in ('translate','rotate','scale') for a in 'XYZ')+('rotateOrder','visibility')


def _arm_channel_policy(data):
    import maya.cmds as c
    if data['kind']!='arm':return
    for role in ('middle_fk','end_fk'):
        for axis in 'XYZ':
            # In Maya 2024, channelBox=True overrides keyable=True even when
            # passed in the same call. Keyable channels are already visible;
            # setting only keyable also includes their curves in the timeline
            # and ordinary key/delete operations.
            c.setAttr(data['controls'][role]+'.translate'+axis,keyable=True)


def _frame(node, create, pivot_source=None):
    import maya.cmds as c
    compose=create('composeMatrix','pivot')
    c.connectAttr((pivot_source or node)+'.rotatePivot',compose+'.inputTranslate')
    matrix=create('multMatrix','pivotWorld')
    c.connectAttr(compose+'.outputMatrix',matrix+'.matrixIn[0]')
    c.connectAttr(node+'.worldMatrix[0]',matrix+'.matrixIn[1]')
    return matrix+'.matrixSum'


def _rollback_extension(data,old):
    import maya.cmds as c
    for entry in reversed(data['entries'][len(old['entries']):]):
        src,dst=entry['source'],entry['proxy']
        if c.isConnected(dst,src):c.disconnectAttr(dst,src)
        if entry['incoming']:
            if c.isConnected(entry['incoming'],dst):c.disconnectAttr(entry['incoming'],dst)
            c.connectAttr(entry['incoming'],src,force=True)
        c.setAttr(src,entry['value'])
    for shape,value in data['hidden_shapes'].items():
        if shape not in old['hidden_shapes'] and c.objExists(shape):c.setAttr(shape+'.lodVisibility',value)
    for node in reversed(data['created'][len(old['created']):]):
        if c.objExists(node):c.delete(node)
    data.clear();data.update(old)


def _add_roll_controls(rig,data):
    import maya.cmds as c
    if data['kind']!='leg' or all(k in data['controls'] for k in ROLL_ROLES):return
    old=json.loads(json.dumps(data));auto=c.autoKeyframe(q=True,state=True)
    pose={n:c.xform(n,q=True,ws=True,m=True) for n in rig['joints']}
    c.autoKeyframe(state=False)
    try:
        _add_roll_controls_impl(rig,data)
        error=max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('脚跟实时层改变了原姿态：'+str(error))
    except Exception:
        _rollback_extension(data,old)
        raise
    finally:c.autoKeyframe(state=auto)


def _toe_frame(source,ball,create):
    """Insert ball motion into toe display position, keeping toe rotation free.

    The solver deliberately keeps toe and ball as siblings. Reading only their
    input matrices here avoids feedback into the solver or its orient constraints.
    """
    import maya.cmds as c
    moved=create('multMatrix','toePosition')
    for i,plug in enumerate((_frame(source,create),ball+'.parentInverseMatrix[0]',
                              ball+'.matrix',ball+'.parentMatrix[0]')):
        c.connectAttr(plug,moved+'.matrixIn[{}]'.format(i))
    position=create('pickMatrix','toePositionOnly')
    c.connectAttr(moved+'.matrixSum',position+'.inputMatrix')
    for attr in ('useRotate','useScale','useShear'):c.setAttr(position+'.'+attr,False)
    axes=create('pickMatrix','toeAxes')
    c.connectAttr(source+'.worldMatrix[0]',axes+'.inputMatrix');c.setAttr(axes+'.useTranslate',False)
    frame=create('multMatrix','toeFrame')
    c.connectAttr(axes+'.outputMatrix',frame+'.matrixIn[0]')
    c.connectAttr(position+'.outputMatrix',frame+'.matrixIn[1]')
    return frame+'.matrixSum'


def _add_roll_controls_impl(rig,data):
    """Reverse-foot handles use material pivot points in the final foot frame.

    The input heel stays above toe_end in the solver. Its independent visible
    handle follows both rolls; feeding that world matrix back would be cyclic.
    live_edit rebases inputs before the next gesture instead.
    """
    import maya.cmds as c
    if data['kind']!='leg':return
    ns=rig['namespace'];side=rig.get('side','L')
    group=c.listRelatives(data['controls']['foot'],parent=True,fullPath=True)[0]
    def create(kind,label,**kwargs):
        n=c.createNode(kind,name=ns+':live_'+label,skipSelect=True,**kwargs)
        data['created'].append(n);return n
    for role in ROLL_ROLES:
        if role in data['controls']:continue
        source=rig['controls'][role];target=ns+':ik_connect_'+side+'1'
        proxy=c.createNode('transform',name=source.rsplit('|',1)[-1]+'_live',parent=group,skipSelect=True)
        data['created'].append(proxy)
        for attr in CHANNELS:
            src=source+'.'+attr;dst=proxy+'.'+attr
            value=c.getAttr(src);locked=c.getAttr(src,lock=True)
            incoming=c.connectionInfo(src,sourceFromDestination=True)
            if incoming and not c.nodeType(incoming.split('.')[0]).startswith('animCurve'):
                raise ValueError('脚部实时控制器不覆盖外部驱动：'+src)
            c.setAttr(dst,value,keyable=c.getAttr(src,keyable=True),channelBox=c.getAttr(src,channelBox=True))
            if locked:
                c.setAttr(dst,lock=True);continue
            data['entries'].append(dict(source=src,proxy=dst,incoming=incoming,value=value))
            if incoming:c.disconnectAttr(incoming,src);c.connectAttr(incoming,dst)
            c.connectAttr(dst,src)
            c.setAttr(dst,value)
        c.addAttr(proxy,ln='liveInput',at='message');c.connectAttr(source+'.message',proxy+'.liveInput')
        c.addAttr(proxy,ln='liveAlignment',proxy=rig['root']+'.liveAlignment',keyable=True)
        for attr in c.listAttr(source,userDefined=True,keyable=True) or []:
            if c.attributeQuery(attr,node=source,numberOfChildren=True):continue
            if not c.objExists(proxy+'.'+attr):c.addAttr(proxy,ln=attr,proxy=source+'.'+attr,keyable=True)
        choice=create('choice',role+'_frame')
        c.connectAttr(_frame(source,create),choice+'.input[0]')
        desired=(_toe_frame(source,rig['controls']['ball'],create) if role=='toe'
                 else _frame(target,create,pivot_source=source))
        c.connectAttr(desired,choice+'.input[1]')
        c.connectAttr(rig['root']+'.liveAlignment',choice+'.selector')
        follow=create('multMatrix',role+'_follow')
        c.connectAttr(proxy+'.inverseMatrix',follow+'.matrixIn[0]')
        c.connectAttr(choice+'.output',follow+'.matrixIn[1]')
        c.connectAttr(group+'.worldInverseMatrix[0]',follow+'.matrixIn[2]')
        c.connectAttr(follow+'.matrixSum',proxy+'.offsetParentMatrix')
        _artwork(source,proxy,create)
        for shape in c.listRelatives(source,s=True,f=True) or []:
            if c.nodeType(shape) not in ('nurbsCurve','locator'):continue
            data['hidden_shapes'][shape]=c.getAttr(shape+'.lodVisibility')
            c.setAttr(shape+'.lodVisibility',False)
        data['controls'][role]=proxy;data['inputs'][role]=source;data['targets'][role]=target
        if role=='toe':data.setdefault('toe_follow',{})[role]=rig['controls']['ball']
        else:data.setdefault('pivot_sources',{})[role]=source


def _artwork(source, proxy, create):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .controller_shapes import capture_control, _set_display
    artwork=capture_control(source)
    scale=om.MTransformationMatrix(om.MMatrix(c.xform(proxy,q=True,ws=True,m=True))).scale(om.MSpace.kWorld)
    _set_display(proxy,artwork['display'])
    for i,item in enumerate(artwork['shapes']):
        name=proxy.rsplit('|',1)[-1]+'Shape'+str(i)
        if item['type']=='nurbsCurve':
            temp=c.curve(name=proxy.rsplit(':',1)[0]+':liveCurveTemp',degree=item['degree'],
                         pointWeight=[tuple(p[a]/scale[a] for a in range(3))+(p[3],) for p in item['points']],
                         knot=item['knots'],periodic=item['form']==3)
            try:
                if item['form']==2:c.closeCurve(temp,ch=False,rpo=True,preserveShape=True)
                shape=c.listRelatives(temp,s=True,f=True)[0]
                shape=c.parent(shape,proxy,shape=True,relative=True)[0]
                shape=c.rename(shape,name)
            finally:c.delete(temp)
        else:
            shape=create('locator','shape',parent=proxy)
            c.setAttr(shape+'.localPosition',*[v/scale[a] for a,v in enumerate(item['position'])])
            c.setAttr(shape+'.localScale',*[v/abs(scale[a]) for a,v in enumerate(item['size'])])
        _set_display(shape,item['display'])
        c.setAttr(shape+'.visibility',item['visibility'])


def enable(rig, kind):
    """Add surfaces to our arm/leg, preserving existing curves and input names."""
    import maya.cmds as c
    if kind not in ('arm','leg'):raise ValueError('实时对齐仅用于手臂和腿部。')
    root=rig['root'];ns=rig['namespace'];side=rig.get('side','L')
    if c.objExists(root+'.liveAlignmentData'):
        data=json.loads(c.getAttr(root+'.liveAlignmentData'))
        if not all(c.objExists(n) for n in data['controls'].values()):raise ValueError('实时控制器不完整，请先撤销删除操作。')
        from . import live_edit
        live_edit.install()
        old_count=len(data['created'])
        if kind=='leg':_add_roll_controls(rig,data)
        if data.get('version')!=VERSION or old_count!=len(data['created']):
            data.update(version=VERSION,interaction='native_manual_alignment' if kind=='arm' else 'native_viewport_input_rebase')
            c.setAttr(root+'.liveAlignmentData',lock=False)
            c.setAttr(root+'.liveAlignmentData',json.dumps(data),type='string',lock=True)
        c.setAttr(root+'.liveAlignment',True)
        _arm_channel_policy(data)
        rig['live_alignment']=data;rig['live_controls']=data['controls']
        rig.setdefault('nodes',[]).extend(data['created'][old_count:])
        return data
    roles={'shoulder_fk':ns+':base_'+side+'1','middle_fk':ns+':base_'+side+'2',
           'end_fk':ns+':base_'+side+'3'} if kind=='arm' else {'foot':ns+':ik_connect_'+side+'1'}
    for role,target in roles.items():
        source=rig['controls'][role]
        if not c.objExists(target):raise ValueError('缺少实时对齐参考：'+target)
        for attr in CHANNELS:
            plug=source+'.'+attr
            incoming=c.connectionInfo(plug,sourceFromDestination=True)
            if incoming and not c.nodeType(incoming.split('.')[0]).startswith('animCurve'):
                raise ValueError('实时对齐不覆盖控制器外部驱动：'+plug)
    before={n:c.xform(n,q=True,ws=True,m=True) for n in rig.get('joints',[])}
    created=[];entries=[];surfaces={};hidden={};hidden_connections={};joint_styles={}
    frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    def create(kind,label,**kwargs):
        n=c.createNode(kind,name=ns+':live_'+label,skipSelect=True,**kwargs);created.append(n);return n
    c.undoInfo(openChunk=True,chunkName='EnableLiveLimbAlignment')
    try:
        c.autoKeyframe(state=False)
        c.addAttr(root,ln='liveAlignment',at='bool',dv=True,keyable=True)
        group=create('transform','controls',parent=root)
        for role,target in roles.items():
            source=rig['controls'][role]
            proxy=c.createNode('transform',name=source.rsplit('|',1)[-1]+'_live',parent=group,skipSelect=True)
            created.append(proxy);surfaces[role]=proxy
            # These are plain transforms: a zero pivot is located exactly on the
            # followed pivot. Original jointOrient/foot pivots stay in the solver.
            for attr in CHANNELS:
                plug=source+'.'+attr;destination=proxy+'.'+attr
                value=c.getAttr(plug);locked=c.getAttr(plug,lock=True)
                c.setAttr(destination,value)
                c.setAttr(destination,keyable=c.getAttr(plug,keyable=True),channelBox=c.getAttr(plug,channelBox=True))
                if locked:
                    c.setAttr(destination,lock=True)
                    continue
                incoming=c.connectionInfo(plug,sourceFromDestination=True)
                entry=dict(source=plug,proxy=destination,incoming=incoming,value=value)
                entries.append(entry)
                if incoming:
                    c.disconnectAttr(incoming,plug);c.connectAttr(incoming,destination)
                c.connectAttr(destination,plug)
            # Proxy attributes expose global and animationOffset without copying
            # their animation or changing the original downstream connections.
            for attr in c.listAttr(source,userDefined=True,keyable=True) or []:
                if c.attributeQuery(attr,node=source,numberOfChildren=True):continue
                if not c.objExists(proxy+'.'+attr):c.addAttr(proxy,ln=attr,proxy=source+'.'+attr,keyable=True)
            c.addAttr(proxy,ln='liveAlignment',proxy=root+'.liveAlignment',keyable=True)
            c.addAttr(proxy,ln='liveInput',at='message');c.connectAttr(source+'.message',proxy+'.liveInput')
            choice=create('choice',role+'_frame')
            c.connectAttr(_frame(source,create),choice+'.input[0]')
            target_frame=_frame(target,create)
            if kind=='leg':
                # Keep the foot's roll axes, but follow the solved ankle even
                # when reach limits/softness separate it from the IK input.
                rotation=create('pickMatrix','footAxes')
                c.connectAttr(target_frame,rotation+'.inputMatrix');c.setAttr(rotation+'.useTranslate',False)
                position=create('pickMatrix','anklePosition')
                c.connectAttr(rig['joints'][2]+'.worldMatrix[0]',position+'.inputMatrix')
                for attr in ('useRotate','useScale','useShear'):c.setAttr(position+'.'+attr,False)
                desired=create('multMatrix','solvedAnkle')
                c.connectAttr(rotation+'.outputMatrix',desired+'.matrixIn[0]')
                c.connectAttr(position+'.outputMatrix',desired+'.matrixIn[1]')
                target_frame=desired+'.matrixSum'
            c.connectAttr(target_frame,choice+'.input[1]')
            c.connectAttr(root+'.liveAlignment',choice+'.selector')
            follow=create('multMatrix',role+'_follow')
            # inverseMatrix is local and excludes offsetParentMatrix. No edge
            # from the surface world transform goes back to the input graph.
            c.connectAttr(proxy+'.inverseMatrix',follow+'.matrixIn[0]')
            c.connectAttr(choice+'.output',follow+'.matrixIn[1]')
            c.connectAttr(group+'.worldInverseMatrix[0]',follow+'.matrixIn[2]')
            c.connectAttr(follow+'.matrixSum',proxy+'.offsetParentMatrix')
            _artwork(source,proxy,create)
            for shape in c.listRelatives(source,s=True,f=True) or []:
                if c.nodeType(shape) not in ('nurbsCurve','locator'):continue
                incoming=c.connectionInfo(shape+'.lodVisibility',sfd=True)
                if incoming and c.objExists(root+'.armWorldIKData') and incoming==ns+':worldIK_visibility.outputX':
                    hidden_connections[shape]=incoming;c.disconnectAttr(incoming,shape+'.lodVisibility')
                hidden[shape]=c.getAttr(shape+'.lodVisibility');c.setAttr(shape+'.lodVisibility',False)
            if c.nodeType(source)=='joint':
                joint_styles[source]=c.getAttr(source+'.drawStyle');c.setAttr(source+'.drawStyle',2)
        error=max([abs(a-b) for n,m in before.items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)]+[0])
        if error>1e-5:raise RuntimeError('实时对齐改变了原姿态：'+str(error))
        data=dict(version=VERSION,kind=kind,root=root,controls=surfaces,inputs={k:rig['controls'][k] for k in roles},
                  targets=roles,position_targets={'foot':rig['joints'][2]} if kind=='leg' else {},
                  created=created,entries=entries,hidden_shapes=hidden,hidden_connections=hidden_connections,joint_styles=joint_styles)
        _add_roll_controls(rig,data)
        c.addAttr(root,ln='liveAlignmentData',dt='string')
        c.setAttr(root+'.liveAlignmentData',json.dumps(data),type='string',lock=True)
        _arm_channel_policy(data)
        rig['live_alignment']=data;rig['live_controls']=surfaces
        rig.setdefault('nodes',[]).extend(created)
        from . import live_edit
        live_edit.install()
        if kind=='arm':
            from .arm_ik import refresh_surfaces
            refresh_surfaces(root,surfaces)
        return data
    except Exception:
        for e in reversed(entries):
            if c.isConnected(e['proxy'],e['source']):c.disconnectAttr(e['proxy'],e['source'])
            if e['incoming']:
                if c.isConnected(e['incoming'],e['proxy']):c.disconnectAttr(e['incoming'],e['proxy'])
                c.connectAttr(e['incoming'],e['source'],force=True)
            else:c.setAttr(e['source'],e['value'])
        for s,v in hidden.items():c.setAttr(s+'.lodVisibility',v)
        for s,p in hidden_connections.items():c.connectAttr(p,s+'.lodVisibility',force=True)
        for n,v in joint_styles.items():c.setAttr(n+'.drawStyle',v)
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        if c.objExists(root+'.liveAlignmentData'):
            c.setAttr(root+'.liveAlignmentData',lock=False);c.deleteAttr(root+'.liveAlignmentData')
        if c.objExists(root+'.liveAlignment'):c.deleteAttr(root+'.liveAlignment')
        raise
    finally:
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        c.undoInfo(closeChunk=True)


def remove(root):
    """Remove the surface layer, returning current channels/curves to old controls."""
    import maya.cmds as c
    if not c.objExists(root+'.liveAlignmentData'):return
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    if any(c.objExists(n+'.liveRotationData') for n in data['inputs'].values()):
        raise ValueError('这套手臂已有独立旋转动画层。请使用 liveAlignment=0 关闭实时显示；移除操作层前需先烘焙旋转结果。')
    auto=c.autoKeyframe(q=True,state=True)
    c.undoInfo(openChunk=True,chunkName='RemoveLiveLimbAlignment')
    try:
        c.autoKeyframe(state=False)
        for e in data['entries']:
            incoming=c.connectionInfo(e['proxy'],sourceFromDestination=True);value=c.getAttr(e['proxy'])
            c.disconnectAttr(e['proxy'],e['source'])
            if incoming:
                c.disconnectAttr(incoming,e['proxy']);c.connectAttr(incoming,e['source'])
            else:c.setAttr(e['source'],value)
        for s,v in data['hidden_shapes'].items():
            if c.objExists(s):c.setAttr(s+'.lodVisibility',v)
        for s,p in data.get('hidden_connections',{}).items():
            if c.objExists(s):c.connectAttr(p,s+'.lodVisibility',force=True)
        for n,v in data['joint_styles'].items():c.setAttr(n+'.drawStyle',v)
        for n in reversed(data['created']):
            if c.objExists(n):c.delete(n)
        c.setAttr(root+'.liveAlignmentData',lock=False);c.deleteAttr(root+'.liveAlignmentData')
        c.deleteAttr(root+'.liveAlignment')
        if data['kind']=='arm':
            from .arm_ik import refresh_surfaces
            refresh_surfaces(root,data['inputs'])
    finally:
        c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)


def editable_plug(plug):
    """Follow only our verified source-to-live channel relay after migration."""
    import maya.cmds as c
    incoming=c.connectionInfo(plug,sourceFromDestination=True)
    if incoming:
        node=incoming.split('.')[0]
        if c.objExists(node+'.liveInput'):
            inputs=c.listConnections(node+'.liveInput',s=True,d=False) or []
            if inputs and c.ls(inputs[0],long=True)==c.ls(plug.split('.')[0],long=True):return incoming
    return plug


def enable_character(root):
    """Explicitly upgrade an existing character, auditing its animation in place."""
    import maya.cmds as c
    old_text=c.getAttr(root+'.integratedRigData');rig=json.loads(old_text)
    parts={k:p for k,p in rig['parts'].items() if k.startswith(('arm_','leg_'))}
    controls=[n for p in rig['parts'].values() for n in p['controls'].values()]
    controls += [n for p in rig['parts'].values() for n in p.get('live_controls',{}).values()]
    # Scrubbing for the audit must not discard the user's unkeyed test pose.
    current_values={}
    for node in controls:
        for attr in c.listAttr(node,keyable=True,scalar=True) or []:
            plug=node+'.'+attr
            if attr=='liveAlignment' or c.getAttr(plug,lock=True):continue
            incoming=c.connectionInfo(plug,sourceFromDestination=True)
            if incoming and not c.nodeType(incoming.split('.')[0]).startswith('animCurve'):continue
            value=c.getAttr(plug)
            if isinstance(value,(int,float,bool)):current_values[plug]=value
    targets=list({m['target'] for p in rig['parts'].values() for m in p.get('original_target_mapping',[])})
    frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    times=sorted(set([frame]+(c.keyframe(controls,q=True,tc=True) or [])))
    times=sorted(set(times+[(a+b)/2 for a,b in zip(times,times[1:])]))
    curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),
               c.keyTangent(n,q=True,inTangentType=True),c.keyTangent(n,q=True,outTangentType=True))
            for n in c.ls(type='animCurve')}
    baseline={};added=[];flags={};old_live={};error=0
    current_pose={n:c.xform(n,q=True,ws=True,m=True) for n in targets}
    c.undoInfo(openChunk=True,chunkName='EnableCharacterLiveAlignment')
    try:
        c.autoKeyframe(state=False)
        for f in times:
            c.currentTime(f);baseline[f]={n:c.xform(n,q=True,ws=True,m=True) for n in targets}
        c.currentTime(frame)
        for key,part in parts.items():
            if c.objExists(part['root']+'.liveAlignmentData'):
                flags[part['root']]=c.getAttr(part['root']+'.liveAlignment')
                old_live[part['root']]=c.getAttr(part['root']+'.liveAlignmentData')
            else:added.append(part['root'])
            enable(part,key.split('_')[0])
        for f in times:
            c.currentTime(f)
            error=max(error,max([abs(a-b) for n,m in baseline[f].items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)]+[0]))
        if error>1e-5:raise RuntimeError('实时控制器改变了已有动画：'+str(error))
        assert curves=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),
                          c.keyTangent(n,q=True,inTangentType=True),c.keyTangent(n,q=True,outTangentType=True))
                       for n in c.ls(type='animCurve')},'Animation curves changed'
        c.currentTime(frame)
        for plug,value in current_values.items():c.setAttr(editable_plug(plug),value)
        current_error=max([abs(a-b) for n,m in current_pose.items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)]+[0])
        if current_error>1e-5:raise RuntimeError('实时升级未能保留当前未打帧姿态：'+str(current_error))
        report=dict(version=VERSION,parts=list(parts),sample_frames=len(times),max_world_error=error,
                    current_pose_error=current_error,curves_preserved=len(curves),controls=sum(len(p['live_controls']) for p in parts.values()))
        rig['live_alignment_upgrade']=report
        c.setAttr(root+'.integratedRigData',lock=False)
        c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
        mapping={c.ls(p['controls'][role],long=True)[0]:node for p in parts.values() for role,node in p['live_controls'].items()}
        selection=[mapping.get(n,n) for n in selection]
        return report
    except Exception:
        for part_root in reversed(added):remove(part_root)
        for part_root,value in flags.items():c.setAttr(part_root+'.liveAlignment',value)
        for part_root,value in old_live.items():
            old_data=json.loads(value)
            new_data=json.loads(c.getAttr(part_root+'.liveAlignmentData'))
            if len(new_data['created'])>len(old_data['created']):_rollback_extension(new_data,old_data)
            c.setAttr(part_root+'.liveAlignmentData',lock=False)
            c.setAttr(part_root+'.liveAlignmentData',value,type='string',lock=True)
        c.setAttr(root+'.integratedRigData',lock=False)
        c.setAttr(root+'.integratedRigData',old_text,type='string',lock=True)
        raise
    finally:
        c.currentTime(frame)
        for plug,value in current_values.items():
            if c.objExists(plug):c.setAttr(editable_plug(plug),value)
        c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        c.undoInfo(closeChunk=True)
