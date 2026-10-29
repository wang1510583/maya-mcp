"""Make animator curves editable in the shot without editing reference assets.

Native setKeyframe can return zero for a referenced animCurve. Preserve the
entire curve in a local duplicate, route only registered animator inputs to it,
and keep all existing time drivers (including time warps) intact.
"""


def _plugs():
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import scene_data
    controls=set(c.ls('::*.zeroChannelData',objectsOnly=True,long=True) or [])
    for root in c.ls('::*.integratedRigData',objectsOnly=True) or []:
        rig=scene_data.read(root+'.integratedRigData')
        for part in rig.get('parts',{}).values():
            controls.update((part.get('zero_controls') or part.get('live_controls') or part.get('controls',{})).values())
        controls.update(row.get('control') for row in rig.get('generic_objects',[]) if row.get('control'))
        if rig.get('master_control'):controls.add(rig['master_control'])
    plugs=set()
    for node in controls:
        if not c.objExists(node):continue
        for attr in c.listAttr(node,keyable=True,scalar=True,unlocked=True) or []:
            plug=node+'.'+attr;seen=set()
            while plug not in seen:
                seen.add(plug);selection=om.MSelectionList();selection.add(plug)
                if not om.MFnAttribute(selection.getPlug(0).attribute()).isProxyAttribute:break
                source=c.connectionInfo(plug,sfd=True)
                if not source:break
                plug=source
            if not c.getAttr(plug,lock=True):plugs.add(plug)
    return plugs


def prepare():
    import maya.cmds as c
    from . import live_layers,arm_ik
    plugs=_plugs();layers=live_layers.blend_nodes();curves={};visited=set()
    def walk(destination):
        if destination in visited:return
        visited.add(destination)
        source=c.connectionInfo(destination,sfd=True)
        if not source:return
        node=source.split('.')[0];kind=c.nodeType(node)
        if kind.startswith('animCurveT'):
            if c.referenceQuery(node,isNodeReferenced=True) or not c.connectionInfo(node+'.input',sfd=True):
                curves.setdefault(node,[]).append((source,destination))
        elif kind=='unitConversion':walk(node+'.input')
        elif node in layers:
            for attr in ('inputA','inputB'):
                for child in c.attributeQuery(attr,node=node,listChildren=True) or [attr]:walk(node+'.'+child)
    for plug in plugs:walk(plug)
    # Respect intentional locks; never make read-only user channels editable.
    curves={node:edges for node,edges in curves.items() if not any(c.lockNode(node,q=True,lock=True))
            and not c.getAttr(node+'.input',lock=True)
            and all(not c.getAttr(dst,lock=True) and not any(c.lockNode(dst.split('.')[0],q=True,lock=True)) for _,dst in edges)}
    if not curves:return dict(cloned=[],time_connected=[])
    if not c.objExists('time1.outTime'):raise ValueError('找不到 Maya 场景时间节点，未修改动画曲线。')
    # Only restore the affected animator channels, including unkeyed edits.
    values={p:c.getAttr(p) for p in plugs}
    created=[];connections=[];cloned=[];timed=[]
    selection=c.ls(selection=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    c.undoInfo(openChunk=True,chunkName='PrepareEditableRigAnimation')
    c.autoKeyframe(state=False);arm_ik._busy=True
    try:
        for source,edges in curves.items():
            curve=source
            if c.referenceQuery(source,isNodeReferenced=True):
                curve=c.duplicate(source,inputConnections=True,name='bencaoShotAnimation#')[0]
                created.append(curve);cloned.append(dict(source=source,curve=curve))
            if not c.connectionInfo(curve+'.input',sfd=True):
                c.connectAttr('time1.outTime',curve+'.input');timed.append(curve)
            if curve!=source:
                for old,dst in edges:
                    c.connectAttr(curve+'.output',dst,force=True);connections.append((old,dst))
        for p,v in values.items():
            if isinstance(v,(int,float,bool)) and c.getAttr(p)!=v:c.setAttr(p,v)
        return dict(cloned=cloned,time_connected=timed)
    except Exception:
        for old,dst in reversed(connections):c.connectAttr(old,dst,force=True)
        for curve in timed:
            if curve not in created and c.isConnected('time1.outTime',curve+'.input'):c.disconnectAttr('time1.outTime',curve+'.input')
        if created:c.delete(created)
        for p,v in values.items():
            if isinstance(v,(int,float,bool)) and c.getAttr(p)!=v:c.setAttr(p,v)
        raise
    finally:
        if (c.ls(selection=True,long=True) or [])!=selection:
            c.select(selection,r=True) if selection else c.select(clear=True)
        arm_ik._busy=busy;c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)
