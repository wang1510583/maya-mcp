"""Matched FK/world-IK inputs for the existing soft arm solver.

Only explicit channel edits perform matching. Animated mode evaluation and
playback are ordinary Maya choice/constraint graphs, with no per-frame writes.
"""
import json
import math

VERSION='1.1.0'
TR=tuple(p+a for p in ('translate','rotate') for a in 'XYZ')
if '_callbacks' not in globals():_callbacks={}
if '_scene_callbacks' not in globals():_scene_callbacks=[]
if '_busy' not in globals():_busy=False
if '_scene_callback_version' not in globals():_scene_callback_version=0
if '_pending' not in globals():_pending={}


def _switch_module(root):
    import maya.cmds as c
    if c.objExists(root+'.chestSpaceData'):
        from . import chest_space
        return chest_space
    if c.objExists(root+'.bodyDriveData'):
        from . import body_direction
        return body_direction
    if c.objExists(root+'.matchedSpaceData'):
        from . import head_knee_space
        return head_knee_space
    if c.objExists(root+'.upperArmSpaceData'):
        from . import upper_arm_space
        return upper_arm_space
    if c.objExists(root+'.footSpaceData'):
        from . import foot_space
        return foot_space
    import sys
    return sys.modules[__name__]


def _has_mode(root):
    import maya.cmds as c
    return any(c.objExists(root+'.'+a) for a in ('armWorldIKData','footSpaceData','upperArmSpaceData','matchedSpaceData','bodyDriveData','chestSpaceData'))


def _sync_mode_cache():
    import maya.cmds as c
    if _busy or _pending:return
    for root,entry in list(_callbacks.items()):
        if _has_mode(root):
            entry.update(value=c.getAttr(_switch_module(root)._data(root)['global_plug']),time=c.currentTime(q=True))


def _finish_channel_switch(root):
    """Evaluate the solve after Maya has finished the initiating channel edit."""
    import maya.cmds as c
    pending=_pending.pop(root,None)
    if pending is None:return
    try:
        if _has_mode(root):
            _switch_module(root).switch(root,pending['new'],previous=pending['old'])
    except Exception as exc:c.warning(str(exc))
    finally:
        c.undoInfo(closeChunk=True)
        if not _pending:c.refresh(suspend=False)


def _data(root):
    import maya.cmds as c
    return json.loads(c.getAttr(root+'.armWorldIKData'))


def _mode(value):return int(value>=.5)


def enable(rig,callbacks=True):
    """Add independent goals; preserve the FK graph and all existing curves."""
    import maya.cmds as c
    from .live_alignment import _artwork
    root=rig['root'];ns=rig['namespace'];side=rig.get('side','L')
    if c.objExists(root+'.armWorldIKData'):
        if callbacks:install()
        return _data(root)
    from . import live_edit
    live_edit.install()
    source=rig['controls']['end_fk'];wrist=rig.get('live_controls',{}).get('end_fk',source)
    hand=rig['controls']['end_locator'];pole=rig['controls']['pole_locator']
    plug=source+'.global';created=[];edges=[];shapes=[];added=[];static={}
    if c.objExists(plug) and _mode(c.getAttr(plug)):
        raise ValueError('安装世界 IK 前请将手腕 global 设为 0；旧空间动画需先保留。')
    auto=c.autoKeyframe(q=True,state=True);selection=c.ls(sl=True,long=True) or []
    baseline={n:c.xform(n,q=True,ws=True,m=True) for n in rig['joints']}
    def create(kind,label,**kwargs):
        node=c.createNode(kind,name=ns+':worldIK_'+label,skipSelect=True,**kwargs);created.append(node);return node
    c.undoInfo(openChunk=True,chunkName='EnableArmWorldIK');c.autoKeyframe(state=False)
    try:
        if not c.objExists(plug):
            c.addAttr(source,ln='global',nn='global',at='enum',en='0:1',dv=0,keyable=True);added.append(plug)
        if wrist!=source and not c.objExists(wrist+'.global'):
            c.addAttr(wrist,ln='global',proxy=plug,keyable=True);added.append(wrist+'.global')
        mode=create('condition','mode');c.setAttr(mode+'.operation',3);c.setAttr(mode+'.secondTerm',.5)
        c.setAttr(mode+'.colorIfTrueR',1);c.setAttr(mode+'.colorIfFalseR',0);c.connectAttr(plug,mode+'.firstTerm')
        reverse=create('reverse','visibility');c.connectAttr(mode+'.outColorR',reverse+'.inputX')
        controls={}
        for role,original,art in [('wrist',hand,wrist),('pole',pole,pole)]:
            ctrl=create('transform',role,parent=root);c.setAttr(ctrl+'.inheritsTransform',False)
            c.xform(ctrl,ws=True,m=c.xform(original,q=True,ws=True,m=True));controls[role]=ctrl
            for a in ('sx','sy','sz','v'):c.setAttr(ctrl+'.'+a,lock=True,keyable=False,channelBox=False)
            if role=='pole':
                for a in ('rx','ry','rz'):c.setAttr(ctrl+'.'+a,lock=True,keyable=False)
            c.addAttr(ctrl,ln='global',proxy=plug,keyable=True)
            c.addAttr(ctrl,ln='armIKRoot',at='message');c.connectAttr(root+'.message',ctrl+'.armIKRoot')
            _artwork(art,ctrl,create)
            for shape in c.listRelatives(ctrl,s=True,f=True) or []:c.connectAttr(mode+'.outColorR',shape+'.lodVisibility')
            goal=create('transform',role+'Goal',parent=root);c.setAttr(goal+'.inheritsTransform',False);c.setAttr(goal+'.visibility',False)
            choice=create('choice',role+'Choice');c.connectAttr(original+'.worldMatrix[0]',choice+'.input[0]')
            c.connectAttr(ctrl+'.worldMatrix[0]',choice+'.input[1]');c.connectAttr(mode+'.outColorR',choice+'.selector')
            c.connectAttr(choice+'.output',goal+'.offsetParentMatrix')
            # Replace only the registered solver constraints' target fields.
            pairs=c.listConnections(original,s=False,d=True,plugs=True,connections=True) or []
            for src,dst in zip(pairs[::2],pairs[1::2]):
                if '.target[0].target' not in dst or c.nodeType(dst.split('.')[0]) not in ('parentConstraint','pointConstraint'):continue
                attr=src.split('.',1)[1];new=goal+'.'+attr
                c.disconnectAttr(src,dst);c.connectAttr(new,dst);edges.append((src,dst,new))
        # The captured solver clamps reach to its configured stretch allowance.
        # World planting needs enough reach as the shoulder moves away. Feed
        # only its IK branch a dynamic minimum allowance; keep FK unchanged.
        params=rig['controls']['parameters']
        length=create('addDoubleLinear','length')
        for i in (1,2):c.connectAttr(params+'.lenght_joint_'+str(i),length+'.input'+str(i))
        ratio=create('multiplyDivide','reachRatio');c.setAttr(ratio+'.operation',2)
        c.connectAttr(ns+':leng_base.translateX',ratio+'.input1X');c.connectAttr(length+'.output',ratio+'.input2X')
        excess=create('addDoubleLinear','reachExcess');c.connectAttr(ratio+'.outputX',excess+'.input1');c.setAttr(excess+'.input2',-1+1e-5)
        maximum=create('condition','reachMaximum');c.setAttr(maximum+'.operation',2)
        c.connectAttr(excess+'.output',maximum+'.firstTerm');c.connectAttr(params+'.lenght_coeff',maximum+'.secondTerm')
        c.connectAttr(excess+'.output',maximum+'.colorIfTrueR');c.connectAttr(params+'.lenght_coeff',maximum+'.colorIfFalseR')
        reach=create('choice','reachChoice');c.connectAttr(params+'.lenght_coeff',reach+'.input[0]')
        c.connectAttr(maximum+'.outColorR',reach+'.input[1]');c.connectAttr(mode+'.outColorR',reach+'.selector')
        destination=ns+':expression1.input[0]';previous=c.connectionInfo(destination,sfd=True)
        c.disconnectAttr(previous,destination);c.connectAttr(reach+'.output',destination);edges.append((previous,destination,reach+'.output'))
        for ctrl in (wrist,controls['wrist']):
            c.addAttr(ctrl,ln='stretch',proxy=params+'.lenght_coeff',keyable=True);added.append(ctrl+'.stretch')
        # Animated retargeting offsets belong to FK. Freeze the wrist offset on
        # the visible IK control so copied animation cannot move a planted hand.
        output=ns+':animationOutput3';offset_attrs=[];offset_inputs=[]
        if c.objExists(output):
            from .live_edit import _frame
            import maya.api.OpenMaya as om
            parent=c.listRelatives(output,p=True,fullPath=True)[0]
            local=_frame(output)*om.MMatrix(c.getAttr(parent+'.worldInverseMatrix[0]'))
            tm=om.MTransformationMatrix(local);rot=tm.rotation(asQuaternion=True).asEulerRotation()
            values=list(tm.translation(om.MSpace.kTransform))+[math.degrees(v) for v in rot]
            offset_inputs=[c.connectionInfo(output+'.'+a,sourceFromDestination=True) or output+'.'+a for a in TR]
            compose=create('composeMatrix','outputOffset')
            for attr,value in zip(TR,values):
                name='ikOffset'+attr[0].upper()+attr[1:];p=controls['wrist']+'.'+name
                c.addAttr(controls['wrist'],ln=name,at='double',dv=value,keyable=True);offset_attrs.append(p)
                c.connectAttr(p,compose+'.input'+attr[0].upper()+attr[1:])
            matrix=create('multMatrix','outputCompensation');c.connectAttr(output+'.inverseMatrix',matrix+'.matrixIn[0]')
            c.connectAttr(compose+'.outputMatrix',matrix+'.matrixIn[1]')
            choice=create('choice','outputChoice');old=c.connectionInfo(output+'.offsetParentMatrix',sfd=True)
            c.connectAttr(matrix+'.matrixSum',choice+'.input[1]')
            if old:c.disconnectAttr(old,output+'.offsetParentMatrix');c.connectAttr(old,choice+'.input[0]')
            else:
                static[output+'.offsetParentMatrix']=c.getAttr(output+'.offsetParentMatrix')
                rest=create('holdMatrix','outputOriginal')
                c.setAttr(rest+'.inMatrix',*static[output+'.offsetParentMatrix'],type='matrix')
                c.connectAttr(rest+'.outMatrix',choice+'.input[0]')
            c.connectAttr(mode+'.outColorR',choice+'.selector')
            c.connectAttr(choice+'.output',output+'.offsetParentMatrix');edges.append((old,output+'.offsetParentMatrix',choice+'.output'))
        # Keep shoulder and forearm controls visible in both modes. Only the
        # wrist and pole switch artwork to their independent world IK controls.
        for node in [wrist]:
            for shape in c.listRelatives(node,s=True,f=True) or []:
                if c.getAttr(shape+'.lodVisibility') and not c.connectionInfo(shape+'.lodVisibility',sfd=True):
                    c.connectAttr(reverse+'.outputX',shape+'.lodVisibility');shapes.append(shape)
        for shape in c.listRelatives(pole,s=True,f=True) or []:
            if c.getAttr(shape+'.lodVisibility') and not c.connectionInfo(shape+'.lodVisibility',sfd=True):
                c.connectAttr(reverse+'.outputX',shape+'.lodVisibility');shapes.append(shape)
        data=dict(version=VERSION,root=root,namespace=ns,side=side,global_plug=plug,fk_wrist=wrist,
                  controls=controls,inputs=rig['controls'],joints=rig['joints'],created=created,
                  edges=edges,shapes=shapes,added=added,static=static,stretch_plug=params+'.lenght_coeff',reach_plug=reach+'.output',
                  offset_output=output if offset_attrs else None,offset_attrs=offset_attrs,offset_inputs=offset_inputs)
        c.addAttr(root,ln='armWorldIKData',dt='string');c.setAttr(root+'.armWorldIKData',json.dumps(data),type='string',lock=True)
        error=max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('世界 IK 安装未保留姿态：'+str(error))
        rig['world_ik']=data;rig.setdefault('nodes',[]).extend(created)
        from .arm_ik_shared import enable as enable_shared
        enable_shared(root)
        data=_data(root);rig['world_ik']=data
        if callbacks:install()
        return data
    except Exception:
        for src,dst,new in reversed(edges):
            if c.isConnected(new,dst):c.disconnectAttr(new,dst)
            if src:c.connectAttr(src,dst,force=True)
            elif dst in static:c.setAttr(dst,*static[dst],type='matrix')
        for shape in shapes:
            incoming=c.connectionInfo(shape+'.lodVisibility',sfd=True)
            if incoming:c.disconnectAttr(incoming,shape+'.lodVisibility')
            c.setAttr(shape+'.lodVisibility',True)
        for node in reversed(created):
            if c.objExists(node):c.delete(node)
        if c.objExists(root+'.armWorldIKData'):c.setAttr(root+'.armWorldIKData',lock=False);c.deleteAttr(root+'.armWorldIKData')
        for p in reversed(added):
            if c.objExists(p):c.deleteAttr(p)
        raise
    finally:
        c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(cl=True);c.undoInfo(closeChunk=True)


def enable_character(root):
    """Explicit upgrade of an existing all-FK character; never reinterpret old IK-space animation."""
    import maya.cmds as c
    from .live_layers import curves_for_plug
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    arms=[p for k,p in rig['parts'].items() if k.startswith('arm') and not c.objExists(p['root']+'.armWorldIKData')]
    for part in arms:
        plug=part['controls']['end_fk']+'.global'
        if not c.objExists(plug):continue
        if abs(c.getAttr(plug))>1e-8 or any(abs(v)>1e-8 for curve in curves_for_plug(plug) for v in c.keyframe(curve,q=True,vc=True) or []):
            raise ValueError('旧手腕已有非零 global 空间动画，请先保留旧版本，不能直接改释为 IK：'+plug)
    installed=[];c.undoInfo(openChunk=True,chunkName='UpgradeArmWorldIK')
    try:
        for part in arms:installed.append(enable(part,callbacks=False))
        c.setAttr(root+'.integratedRigData',lock=False)
        c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
        install();return dict(root=root,upgraded=[d['root'] for d in installed])
    except Exception:
        # These freshly added controls cannot yet contain user animation.
        for data in reversed(installed):
            for src,dst,new in reversed(data['edges']):
                if c.isConnected(new,dst):c.disconnectAttr(new,dst)
                if src:c.connectAttr(src,dst,force=True)
                elif dst in data['static']:c.setAttr(dst,*data['static'][dst],type='matrix')
            for shape in data['shapes']:
                incoming=c.connectionInfo(shape+'.lodVisibility',sfd=True)
                if incoming:c.disconnectAttr(incoming,shape+'.lodVisibility')
                c.setAttr(shape+'.lodVisibility',True)
            for p in reversed(data['added']):
                if c.objExists(p):c.deleteAttr(p)
            for node in reversed(data['created']):
                if c.objExists(node):c.delete(node)
            c.setAttr(data['root']+'.armWorldIKData',lock=False);c.deleteAttr(data['root']+'.armWorldIKData')
        raise
    finally:c.undoInfo(closeChunk=True)


def _plan(data):
    import maya.cmds as c
    from . import live_edit
    if c.objExists(data['root']+'.liveAlignmentData'):return live_edit._plan(data['root'])
    ns=data['namespace'];side=data['side'];ctrl=data['inputs']
    frames=[(ctrl[r],live_edit._frame(ns+':base_'+side+str(i))) for i,r in enumerate(('shoulder_fk','middle_fk','end_fk'),1)]
    frames.append((ctrl['pole_locator'],live_edit._frame(ctrl['pole_locator'])))
    return {},{},frames,[ctrl['end_locator']],[]


def refresh_surfaces(root,controls):
    """Keep switching selection/visibility valid after adding/removing live surfaces."""
    import maya.cmds as c
    if not c.objExists(root+'.armWorldIKData'):return
    data=_data(root);data['fk_wrist']=controls['end_fk']
    shared=data.get('shared_wrist')
    if shared and shared['control']!=controls['end_fk']:
        from .arm_ik_shared import rebind
        rebind(root,controls['end_fk']);data=_data(root)
    for role in ('shoulder_fk','middle_fk','end_fk'):
        for shape in c.listRelatives(controls[role],s=True,f=True) or []:
            visibility=data['namespace']+':worldIK_visibility.outputX'
            incoming=c.connectionInfo(shape+'.lodVisibility',sfd=True)
            if role!='end_fk':
                if incoming==visibility:
                    c.disconnectAttr(incoming,shape+'.lodVisibility')
                    c.setAttr(shape+'.lodVisibility',True)
            else:
                if data.get('shared_wrist'):continue
                if not incoming:c.connectAttr(visibility,shape+'.lodVisibility')
                if shape not in data['shapes']:data['shapes'].append(shape)
    data['shapes']=[s for s in data['shapes'] if c.objExists(s) and c.connectionInfo(s+'.lodVisibility',sfd=True)]
    data['version']=VERSION
    c.setAttr(root+'.armWorldIKData',lock=False)
    c.setAttr(root+'.armWorldIKData',json.dumps(data),type='string',lock=True)


def switch(root,value,key=None,previous=None,_defer_close=False):
    """Match both sides at the current frame; key only when Auto Key is enabled."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import live_edit,live_layers
    global _busy
    if value not in (0,1):raise ValueError('global 仅支持 0（FK）或 1（IK）。')
    data=_data(root);plug=data['global_plug'];new=int(value)
    old=c.getAttr(plug) if previous is None else previous
    if _mode(old)==_mode(new):
        c.setAttr(plug,new);return dict(changed=False)
    busy=_busy;_busy=True;auto=c.autoKeyframe(q=True,state=True);key=auto if key is None else key
    c.undoInfo(openChunk=True,chunkName='MatchArmWorldIK');c.autoKeyframe(state=False);snapshot=None
    try:
        fences=[];live_edit._fence('before',fences)
        c.setAttr(plug,old)
        _,dest,frames,zero,restore=_plan(data)
        nodes=list(dict.fromkeys([n for n,m in frames+restore]+zero+list(data['controls'].values())))
        plugs=[dest.get(n+'.'+a,n+'.'+a) for n in nodes for a in TR]
        plugs+=data['offset_attrs']+data['offset_inputs']+[plug,data['stretch_plug']]
        snapshot=live_edit._snapshot(plugs)
        fences.append(snapshot)
        baseline={n:c.xform(n,q=True,ws=True,m=True) for n in data['joints']+([data['offset_output']] if data['offset_output'] else [])}
        if _mode(new):
            for role,node in [('wrist',data['inputs']['end_locator']),('pole',data['inputs']['pole_locator'])]:
                target=data['controls'][role];matrix=live_edit._frame(node)
                if role=='pole':c.xform(target,ws=True,t=list(matrix)[12:15])
                else:
                    values=list(matrix);values[12:15]=c.xform(data['joints'][-1],q=True,ws=True,t=True)
                    c.xform(target,ws=True,m=values)
            if data['offset_output']:
                node=data['offset_output'];parent=c.listRelatives(node,p=True,fullPath=True)[0]
                tm=om.MTransformationMatrix(live_edit._frame(node)*om.MMatrix(c.getAttr(parent+'.worldInverseMatrix[0]')))
                values=list(tm.translation(om.MSpace.kTransform))+[math.degrees(v) for v in tm.rotation(asQuaternion=True).asEulerRotation()]
                for p,v in zip(data['offset_attrs'],values):c.setAttr(p,v)
            c.setAttr(plug,new)
        else:
            pole_matrix=live_edit._frame(data['controls']['pole'])
            end_matrix=live_edit._frame(data['controls']['wrist'])
            c.setAttr(data['stretch_plug'],c.getAttr(data['reach_plug']))
            c.setAttr(plug,new)
            # Match the solver's exact endpoint/pole inputs first. Rebuilding
            # an already softened/stretched pose solely from output bones can
            # change its solve.
            for attr in TR:
                p=data['inputs']['end_locator']+'.'+attr
                if not c.getAttr(p,lock=True):
                    from .zero_channels import absolute
                    absolute(p,0)
            live_edit._world(data['inputs']['end_fk'],end_matrix,dest)
            pole=data['inputs']['pole_locator']
            desired=list(live_edit._frame(pole));desired[12:15]=list(pole_matrix)[12:15]
            live_edit._world(pole,om.MMatrix(desired),dest)
            for src,dst in zip(data['offset_attrs'],data['offset_inputs']):c.setAttr(dst,c.getAttr(src))
            # Keep the exact solver goals. Normal live manipulation can rebase
            # FK on the next gesture; doing it here can change a softened pose.
        error=max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('FK / IK 对齐未保留姿态，已回退：'+str(error))
        if key:
            force=[plug]
            if _mode(new):force+=data['offset_attrs']+[n+'.'+a for n in data['controls'].values() for a in TR if not c.getAttr(n+'.'+a,lock=True)]
            live_layers.key_mode_switch(snapshot,plug,force)
        live_edit._fence('after',[live_edit._snapshot(snapshot[0])])
        selected=c.ls(sl=True,long=True) or []
        candidates={data['fk_wrist'],data['inputs']['end_fk'],data['controls']['wrist'],data['controls']['pole']}
        destination=data['fk_wrist'] if data.get('shared_wrist') else data['controls']['wrist'] if _mode(new) else data['fk_wrist']
        from .zero_channels import surface
        candidates.update(surface(n) for n in list(candidates));destination=surface(destination)
        if data.get('shared_pole'):
            pole_destination=data['shared_pole']['control']
            pole_candidates={data['controls']['pole'],data['inputs']['pole_locator'],pole_destination}
            selected=[pole_destination if n.rsplit('|',1)[-1] in pole_candidates else n for n in selected]
            candidates.difference_update(pole_candidates)
            c.select(selected,r=True) if selected else None
        if any(n.rsplit('|',1)[-1] in candidates for n in selected):
            c.select(list(dict.fromkeys(destination if n.rsplit('|',1)[-1] in candidates else n for n in selected)),r=True)
        return dict(changed=True,mode=_mode(new),max_pose_error=error)
    except Exception:
        if snapshot:live_edit._restore(snapshot)
        else:c.setAttr(plug,old)
        raise
    finally:
        c.autoKeyframe(state=auto)
        if _defer_close and not c.about(batch=True):
            # An attribute callback runs before Maya records the originating
            # setAttr. Keep this chunk open until that command is recorded, so
            # one Undo includes both the mode edit and its matched transforms.
            import functools,maya.utils
            maya.utils.executeDeferred(functools.partial(c.undoInfo,closeChunk=True))
        else:c.undoInfo(closeChunk=True)
        _busy=busy
        if root in _callbacks:_callbacks[root]['value']=c.getAttr(plug)


def install():
    """Observe explicit channel edits only; evaluation/time changes never match."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    global _scene_callback_version
    if _scene_callback_version!=3:
        for callback in _scene_callbacks:
            try:om.MMessage.removeCallback(callback)
            except RuntimeError:pass
        _scene_callbacks[:]=[];_scene_callback_version=3
    for root,entry in list(_callbacks.items()):
        handle=entry.get('handle')
        if not _has_mode(root) or not handle or not handle.isValid() or not handle.isAlive() or entry.get('version')!=3:
            try:om.MMessage.removeCallback(entry['id'])
            except RuntimeError:pass
            _callbacks.pop(root,None)
    roots=(c.ls('*:rig_root',type='transform') or [])+(c.ls('*.upperArmSpaceData','*:*.upperArmSpaceData','*.matchedSpaceData','*:*.matchedSpaceData','*.bodyDriveData','*:*.bodyDriveData',objectsOnly=True) or [])
    roots+=c.ls('::*.chestSpaceData',objectsOnly=True) or []
    for root in dict.fromkeys(roots):
        if not _has_mode(root) or root in _callbacks:continue
        data=_switch_module(root)._data(root);node,attr=data['global_plug'].rsplit('.',1)
        selection=om.MSelectionList();selection.add(node)
        entry=dict(value=c.getAttr(data['global_plug']),time=c.currentTime(q=True),handle=om.MObjectHandle(selection.getDependNode(0)),version=3)
        def changed(msg,plug,other,client,root=root,attr=attr,entry=entry):
            if not msg&om.MNodeMessage.kAttributeSet or plug.partialName(useLongNames=True)!=attr:return
            if _busy:return
            new=c.getAttr(plug.name());old=entry['value'];entry['value']=new
            if om.MGlobal.isUndoing() or om.MGlobal.isRedoing() or oma.MAnimControl.isPlaying() or oma.MAnimControl.isScrubbing():return
            if root in _pending:
                _pending[root]['new']=new;return
            if entry['time']!=c.currentTime(q=True):entry['time']=c.currentTime(q=True);return
            if _mode(old)==_mode(new):return
            # Attribute callbacks fire inside setAttr before its DG dirtiness
            # has propagated. Nested matching there can read stale matrices.
            # Include the native edit and deferred match in one undo chunk.
            import functools,maya.utils
            c.undoInfo(openChunk=True,chunkName='MatchArmWorldIK')
            _pending[root]=dict(old=old,new=new)
            c.refresh(suspend=True)
            maya.utils.executeDeferred(functools.partial(_finish_channel_switch,root))
        entry['id']=om.MNodeMessage.addAttributeChangedCallback(selection.getDependNode(0),changed)
        _callbacks[root]=entry
    if not _scene_callbacks:
        def history_changed(*args):
            import maya.utils
            maya.utils.executeDeferred(install)
        def time_changed(*args):
            # timeChanged can precede animation evaluation. Reading mode here
            # would cache the previous frame and miss the next channel edit.
            import maya.utils
            maya.utils.executeDeferred(_sync_mode_cache)
        _scene_callbacks.extend([om.MEventMessage.addEventCallback('timeChanged',time_changed),
                                om.MEventMessage.addEventCallback('Undo',history_changed),
                                om.MEventMessage.addEventCallback('Redo',history_changed),
                                om.MSceneMessage.addCallback(om.MSceneMessage.kAfterOpen,lambda *args:install()),
                                om.MSceneMessage.addCallback(om.MSceneMessage.kAfterImport,lambda *args:install())])
    _sync_mode_cache()
    from . import wrist_key_colors
    wrist_key_colors.install()
    from . import switch_panel
    switch_panel.install()
    return len(_callbacks)
