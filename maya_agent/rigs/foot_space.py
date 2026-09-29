"""Matched world/hips spaces on the original foot controller."""
import json

VERSION='1.0.0'


def _data(root):
    import maya.cmds as c
    return json.loads(c.getAttr(root+'.footSpaceData'))


def _enum(plug,proxy):
    import maya.cmds as c
    if c.getAttr(plug,type=True)=='enum':return
    value=int(c.getAttr(plug)>=.5);node=plug.rsplit('.',1)[0]
    pairs=c.listConnections(plug,s=True,d=True,p=True,c=True) or []
    edges=[(a,b) if c.isConnected(a,b) else (b,a) for a,b in zip(pairs[::2],pairs[1::2])]
    for a,b in edges:c.disconnectAttr(a,b)
    if proxy!=plug and c.objExists(proxy):c.deleteAttr(proxy)
    c.deleteAttr(plug);c.addAttr(node,ln='global',nn='global',at='enum',en='0:1',dv=value,keyable=True)
    if proxy!=plug:c.addAttr(proxy.rsplit('.',1)[0],ln='global',proxy=plug,keyable=True)
    for a,b in edges:
        if b!=proxy or proxy==plug:c.connectAttr(a,b,force=True)
    c.setAttr(plug,value)


def enable(rig,space):
    import maya.cmds as c
    from . import arm_ik,live_edit
    root=rig['root']
    if c.objExists(root+'.footSpaceData'):
        rig['foot_space']=_data(root)
        return rig['foot_space']
    source=rig['controls']['foot'];control=rig.get('live_controls',{}).get('foot',source)
    if space['control']!=source:raise ValueError('脚部空间与控制器不匹配。')
    live_edit.install();auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    c.undoInfo(openChunk=True,chunkName='EnableMatchedFootSpace');c.autoKeyframe(state=False);arm_ik._busy=True
    try:
        _enum(space['attribute'],control+'.global')
        data=dict(version=VERSION,root=root,source=source,control=control,global_plug=space['attribute'],
                  driver=space['driver'],group=space['group'],joints=rig['joints'])
        c.addAttr(root,ln='footSpaceData',dt='string');c.setAttr(root+'.footSpaceData',json.dumps(data),type='string',lock=True)
        rig['foot_space']=data
        return data
    finally:
        arm_ik._busy=busy;c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True);arm_ik.install()


def _key(snapshot,plug,old):
    """Key matched local transforms in the chosen layer, guarding the prior frame."""
    import maya.cmds as c
    from . import live_layers
    layer=live_layers.edit_layer();final={p:c.getAttr(p) for p in snapshot[0]}
    changed=[p for p,v in final.items() if abs(v-snapshot[0][p])>1e-8 or p==plug]
    if layer:live_layers.commit(layer,[snapshot],False,force_plugs=[plug])
    # Evaluate guard values in a time context; scrubbing the whole scene would
    # discard unrelated, unkeyed edits on hips and roll controls.
    now=c.currentTime(q=True);guard=now-1
    for p in changed:
        curve=c.animLayer(layer,q=True,findCurveForPlug=p) if layer else c.listConnections(p,s=True,d=False,type='animCurve')
        if curve and c.keyframe(curve,q=True,keyframeCount=True):
            if not c.keyframe(curve,q=True,time=(guard,guard),keyframeCount=True):c.setKeyframe(curve,t=guard,insert=True)
        else:c.setKeyframe(p,t=guard,v=old if p==plug else c.getAttr(p,time=guard),**({'animLayer':layer} if layer else {}))
    for p,v in final.items():c.setAttr(p,v)
    if layer:live_layers.commit(layer,[snapshot],True,force_plugs=[plug])
    else:
        for p in changed:c.setKeyframe(p,v=final[p])
    c.setKeyframe(plug,t=guard,v=old,ott='step',**({'animLayer':layer} if layer else {}))
    curve=c.animLayer(layer,q=True,findCurveForPlug=plug) if layer else c.listConnections(plug,s=True,d=False,type='animCurve')
    if curve:c.keyTangent(curve,e=True,ott='step')
    for p,v in final.items():c.setAttr(p,v)


def switch(root,value,key=None,previous=None):
    import maya.cmds as c
    from . import arm_ik,live_edit
    if value not in (0,1):raise ValueError('脚部 global 仅支持 0（世界）或 1（腰部）。')
    data=_data(root);plug=data['global_plug'];old=c.getAttr(plug) if previous is None else previous
    if old==value:return dict(changed=False)
    auto=c.autoKeyframe(q=True,state=True);key=auto if key is None else key;busy=arm_ik._busy
    arm_ik._busy=True;snapshot=None;edges={};c.undoInfo(openChunk=True,chunkName='MatchFootSpace');c.autoKeyframe(state=False)
    try:
        fences=[];live_edit._fence('before',fences)
        if c.getAttr(plug)!=old:c.setAttr(plug,old)
        source=data['source']
        destinations={}
        if c.objExists(root+'.liveAlignmentData'):
            live=json.loads(c.getAttr(root+'.liveAlignmentData'));destinations={e['source']:e['proxy'] for e in live['entries']}
        plugs=[destinations.get(source+'.'+a,source+'.'+a) for a in live_edit.TR]+[plug]
        snapshot=live_edit._snapshot(plugs);fences.append(snapshot)
        baseline={n:c.xform(n,q=True,ws=True,m=True) for n in data['joints']}
        desired=live_edit._frame(source)
        edges={p:c.connectionInfo(p,sfd=True) for p in snapshot[0] if p!=plug}
        edges={p:e for p,e in edges.items() if e}
        for p,e in edges.items():c.disconnectAttr(e,p);c.setAttr(p,snapshot[0][p])
        c.setAttr(plug,int(value))
        # Finish space constraint evaluation before solving editable local TR.
        c.xform(data['group'],q=True,ws=True,m=True)
        live_edit._world(source,desired,destinations)
        final={p:c.getAttr(p) for p in snapshot[0]}
        for p,e in edges.items():c.connectAttr(e,p)
        for p,v in final.items():c.setAttr(p,v)
        error=max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('脚部空间切换未保留姿态，已回退：'+str(error))
        if key:_key(snapshot,plug,old)
        live_edit._fence('after',[live_edit._snapshot(snapshot[0])])
        return dict(changed=True,mode=int(value),max_pose_error=error)
    except Exception:
        for p,e in edges.items():
            if not c.isConnected(e,p):c.connectAttr(e,p,force=True)
        if snapshot:live_edit._restore(snapshot)
        else:c.setAttr(plug,old)
        raise
    finally:
        c.autoKeyframe(state=auto);arm_ik._busy=busy;c.undoInfo(closeChunk=True)
        arm_ik._sync_mode_cache()


def enable_character(root):
    import maya.cmds as c
    rig=json.loads(c.getAttr(root+'.integratedRigData'));upgraded=[]
    c.undoInfo(openChunk=True,chunkName='EnableCharacterFootSpaces')
    try:
        for key,part in rig['parts'].items():
            if not key.startswith('leg'):continue
            space=next((s for s in rig.get('spaces',[]) if s['control']==part['controls']['foot']),None)
            if space:enable(part,space);upgraded.append(part['root'])
        c.setAttr(root+'.integratedRigData',lock=False);c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
    finally:c.undoInfo(closeChunk=True)
    return upgraded
