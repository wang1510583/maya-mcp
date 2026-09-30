"""Fixed per-mode rest frames; switch matching lives in animator channels."""
import json


def enable(part):
    import maya.cmds as c
    from . import body_direction,body_direction_match,arm_ik,zero_channels,live_edit
    hips=part['controls']['hips'];data=body_direction._data(hips)
    if data.get('fixed_zero'):return data
    offsets=[p for e in data['match_inputs'].values() for group in e['offsets'].values() for p in group]
    # Never reinterpret existing animated space offsets as constant rest data.
    if any(c.connectionInfo(p,sfd=True) or abs(c.getAttr(p))>1e-7 for p in offsets):
        raise ValueError('已有身体切换补偿动画，需保留旧绑定或单独迁移。')
    controls=data['controls'];plugs=[zero_channels.resolve(n+'.'+a) for n in controls for a in live_edit.TR]
    if not part.get('zero_controls'):raise ValueError('固定零位需要已创建的零位身体控制器。')
    if any(abs(c.getAttr(p))>1e-7 for p in plugs):
        raise ValueError('固定零位需在创建时的零位姿态安装。')
    mode=data['global_plug'];chest=data.get('chest_global')
    original=c.getAttr(hips+'.bodyDriveData')
    starts=[hips+'.bodyMatchStart'+str(i) for i in range(4 if chest else 2)]
    saved=live_edit._snapshot(plugs+offsets+starts+[mode]+([chest] if chest else []))
    busy=arm_ik._busy;arm_ik._busy=True;auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    initial_mode=c.getAttr(mode);initial_chest=c.getAttr(chest) if chest else 0
    try:
        for m,s in ((0,0),(1,0),(1,1),(0,1),(initial_mode,initial_chest)):
            if chest and c.getAttr(chest)!=s:body_direction_match.switch(hips,s,key=False,mode_plug=chest)
            if c.getAttr(mode)!=m:body_direction_match.switch(hips,m,key=False)
        data=body_direction._data(hips);data['fixed_zero']=dict(version='1.1.0',frame=c.currentTime(q=True),keying='current_controller_channels')
        c.setAttr(hips+'.bodyDriveData',lock=False);c.setAttr(hips+'.bodyDriveData',json.dumps(data),type='string',lock=True)
        return data
    except Exception:
        live_edit._restore(saved)
        c.setAttr(hips+'.bodyDriveData',lock=False);c.setAttr(hips+'.bodyDriveData',original,type='string',lock=True)
        raise
    finally:
        c.autoKeyframe(state=auto);arm_ik._busy=busy;arm_ik._sync_mode_cache()


def enable_character(root):
    """Explicit safe upgrade of an untouched zero body, never migrate curves."""
    import maya.cmds as c
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    part=rig['parts']['body'];data=enable(part);part['body_drive']=data
    c.setAttr(root+'.integratedRigData',lock=False)
    c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
    return data['fixed_zero']


def switch(control,value,key=None,previous=None,mode_plug=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import body_direction,body_direction_match,arm_ik,live_edit,live_layers,zero_channels
    data=body_direction._data(control);plug=mode_plug or data['global_plug']
    old=c.getAttr(plug) if previous is None else previous
    if old==value:return dict(changed=False)
    auto=c.autoKeyframe(q=True,state=True);key=auto if key is None else key
    busy=arm_ik._busy;arm_ik._busy=True;c.autoKeyframe(state=False)
    c.undoInfo(openChunk=True,chunkName='MatchFixedBodyZero');snapshot=None
    try:
        c.setAttr(plug,old);controls=data['controls']
        modes=list(dict.fromkeys([plug,data['global_plug']]+([data['chest_global']] if data.get('chest_global') else [])))
        raw=modes+[zero_channels.resolve(n+'.'+a) for n in controls for a in live_edit.TR]
        snapshot=live_edit._snapshot(raw);live_edit._fence('before',[snapshot])
        frames={n:live_edit._frame(n) for n in controls}
        baseline={n:c.xform(n,q=True,ws=True,m=True) for n in controls+data['joints']}
        c.setAttr(plug,value)
        order=([controls[0],controls[-1]] if not c.getAttr(data['global_plug']) else [controls[-1],controls[0]])+controls[1:-1]
        for n in order:live_edit._world(n,frames[n],{},solve_translation=False)
        translations=[zero_channels.resolve(n+'.translate'+a) for n in controls for a in 'XYZ']
        def positions():return [v for n in controls for v in list(live_edit._frame(n))[12:15]]
        base=positions();values=[c.getAttr(p) for p in translations];columns=[]
        for p,v in zip(translations,values):
            c.setAttr(p,v+1);columns.append([x-y for x,y in zip(positions(),base)]);c.setAttr(p,v)
        jacobian=list(zip(*columns));wanted=[v for n in controls for v in list(frames[n])[12:15]]
        for _ in range(5):
            residual=[x-y for x,y in zip(wanted,positions())]
            if max(abs(v) for v in residual)<1e-7:break
            correction=body_direction._linear_solve(jacobian,residual)
            for p,v in zip(translations,correction):c.setAttr(p,c.getAttr(p)+v)
        def error():return body_direction_match._check_pose(baseline,{n:c.xform(n,q=True,ws=True,m=True) for n in baseline},om.MDistance(1,om.MDistance.uiUnit()).asCentimeters())
        error()
        if key:live_layers.key_mode_switch(snapshot,plug,force_plugs=raw)
        delta=error();live_edit._fence('after',[live_edit._snapshot(raw)])
        return dict(changed=True,mode=value,max_pose_error=delta,fixed_zero=True)
    except Exception:
        if snapshot:
            registered=live_layers.blend_nodes();new=set()
            for p in snapshot[0]:new.update(live_layers.curves_for_plug(p,registered)-set(snapshot[1]))
            if new:c.delete(list(new))
            live_edit._restore(snapshot)
        raise
    finally:
        c.autoKeyframe(state=auto);arm_ik._busy=busy;c.undoInfo(closeChunk=True);arm_ik._sync_mode_cache()
