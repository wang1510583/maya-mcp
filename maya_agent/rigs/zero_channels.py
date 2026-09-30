"""Zero-based animator surfaces over unchanged solver inputs.

Constant channel offsets preserve every original curve and its interpolation.
The source world matrix only drives the display, never feeds back to the input.
"""
import json

TR=tuple(p+a for p in ('translate','rotate') for a in 'XYZ')


def surface(node):
    import maya.cmds as c
    links=c.listConnections(node+'.zeroSurface',s=True,d=False) if c.objExists(node+'.zeroSurface') else []
    return links[0] if links else node


def resolve(plug):
    node,attr=plug.rsplit('.',1)
    if attr not in TR+('scaleX','scaleY','scaleZ','rotateOrder'):return plug
    import maya.cmds as c
    target=surface(node)
    if target==node:return plug
    data=json.loads(c.getAttr(target+'.zeroChannelData'))
    if attr in ('scaleX','scaleY','scaleZ','rotateOrder'):return target+'.'+attr
    return target+'.'+attr if attr in data['offsets'] else plug


def offset(plug):
    import maya.cmds as c
    node,attr=plug.rsplit('.',1)
    if not c.objExists(node+'.zeroChannelData'):return 0.0
    return json.loads(c.getAttr(node+'.zeroChannelData'))['offsets'].get(attr,0.0)


def absolute(plug,value):
    import maya.cmds as c
    target=resolve(plug);c.setAttr(target,value-offset(target))


def build(rig):
    """Only for freshly built rigs, before user edits or animation layers."""
    import maya.cmds as c
    from . import live_alignment,live_layers
    outputs={};created=[]
    for key,part in rig['parts'].items():
        controls=dict(part['controls']);controls.update(part.get('live_controls',{}))
        group=c.createNode('transform',name=part['namespace']+':zero_controls',parent=part['root']);created.append(group)
        mapping={}
        def create(kind,label,**kwargs):
            n=c.createNode(kind,name=part['namespace']+':zero_'+label,skipSelect=True,**kwargs);created.append(n);return n
        for role,source in controls.items():
            if source in mapping:continue
            if not c.listRelatives(source,s=True):continue
            proxy=c.createNode('transform',name=source.rsplit('|',1)[-1]+'_zero',parent=group,skipSelect=True);created.append(proxy)
            offsets={};edges={};values={a:c.getAttr(source+'.'+a) for a in TR}
            c.setAttr(proxy+'.rotateOrder',c.getAttr(source+'.rotateOrder'))
            for attr in ('scaleX','scaleY','scaleZ','rotateOrder'):
                src=source+'.'+attr;dst=proxy+'.'+attr
                c.setAttr(dst,c.getAttr(src),keyable=c.getAttr(src,keyable=True))
                if c.getAttr(src,lock=True) or c.connectionInfo(src,sfd=True):c.setAttr(dst,lock=True)
                else:c.connectAttr(dst,src)
            for attr in TR:
                src=source+'.'+attr;dst=proxy+'.'+attr;value=values[attr]
                locked=c.getAttr(src,lock=True)
                try:curves=live_layers.curves_for_plug(src)
                except ValueError:curves=None
                if locked or curves is None:
                    c.setAttr(dst,lock=True,keyable=False,channelBox=False);continue
                incoming=c.connectionInfo(src,sfd=True)
                if incoming and not c.nodeType(incoming.split('.')[0]).startswith('animCurve'):
                    raise ValueError('创建零位控制器前不能存在动画层：'+src)
                offsets[attr]=value
                if incoming:
                    c.disconnectAttr(incoming,src);c.connectAttr(incoming,dst)
                    c.keyframe(list(curves),e=True,relative=True,valueChange=-value)
                c.setAttr(dst,0,keyable=c.getAttr(src,keyable=True))
                add=create('animBlendNodeAdditiveDA' if attr.startswith('rotate') else 'animBlendNodeAdditiveDL',role+'_'+attr)
                c.setAttr(add+'.weightA',1);c.setAttr(add+'.weightB',1)
                c.connectAttr(dst,add+'.inputA');c.setAttr(add+'.inputB',value)
                c.connectAttr(add+'.output',src);edges[attr]=c.connectionInfo(src,sfd=True)
                if abs(c.getAttr(src)-value)>1e-7:raise RuntimeError('零位通道改变了输入：'+src)
            for attr in c.listAttr(source,userDefined=True,keyable=True) or []:
                if c.attributeQuery(attr,node=source,numberOfChildren=True):continue
                if not c.objExists(proxy+'.'+attr):c.addAttr(proxy,ln=attr,proxy=source+'.'+attr,keyable=True)
            for attr in ('armSharedWrist','liveInput'):
                if c.objExists(source+'.'+attr):
                    links=c.listConnections(source+'.'+attr,s=True,d=False,p=True) or []
                    if links:c.addAttr(proxy,ln=attr,at='message');c.connectAttr(links[0],proxy+'.'+attr)
            follow=create('multMatrix',role+'_follow')
            c.connectAttr(proxy+'.inverseMatrix',follow+'.matrixIn[0]')
            c.connectAttr(live_alignment._frame(source,create),follow+'.matrixIn[1]')
            c.connectAttr(group+'.worldInverseMatrix[0]',follow+'.matrixIn[2]')
            c.connectAttr(follow+'.matrixSum',proxy+'.offsetParentMatrix')
            visibility=source+'.visibility';ancestor=(c.listRelatives(source,p=True,f=True) or [None])[0]
            while ancestor:
                multiply=create('multDoubleLinear',role+'_visibility')
                c.connectAttr(visibility,multiply+'.input1');c.connectAttr(ancestor+'.visibility',multiply+'.input2')
                visibility=multiply+'.output';ancestor=(c.listRelatives(ancestor,p=True,f=True) or [None])[0]
            c.connectAttr(visibility,proxy+'.visibility');c.setAttr(proxy+'.visibility',keyable=False,channelBox=False)
            # capture_control omits retained solver shapes. Keep precisely the
            # same list when wiring geometry; pairing by type alone binds the
            # new artwork to an older, hidden curve on bodies and knees.
            artwork_shapes=[s for s in c.listRelatives(source,s=True,f=True) or []
                            if c.nodeType(s) in ('nurbsCurve','locator') and c.getAttr(s+'.lodVisibility')]
            live_alignment._artwork(source,proxy,create)
            new_shapes=c.listRelatives(proxy,s=True,f=True) or []
            artwork=create('multMatrix',role+'_artwork')
            c.connectAttr(source+'.worldMatrix[0]',artwork+'.matrixIn[0]')
            c.connectAttr(proxy+'.worldInverseMatrix[0]',artwork+'.matrixIn[1]')
            for index,shape in enumerate(c.listRelatives(source,s=True,f=True) or []):
                plug=shape+'.lodVisibility';incoming=c.connectionInfo(plug,sfd=True)
                matching=[s for s in new_shapes if c.nodeType(s)==c.nodeType(shape)] if shape in artwork_shapes else []
                if matching:
                    new_shape=matching[0];new_shapes.remove(new_shape)
                    if c.nodeType(shape)=='nurbsCurve':
                        geometry=create('transformGeometry',role+'_geometry'+str(index))
                        c.connectAttr(shape+'.local',geometry+'.inputGeometry')
                        c.connectAttr(artwork+'.matrixSum',geometry+'.transform')
                        c.connectAttr(geometry+'.outputGeometry',new_shape+'.create')
                    elif c.nodeType(shape)=='locator':
                        point=create('pointMatrixMult',role+'_locator'+str(index))
                        c.connectAttr(shape+'.localPosition',point+'.inPoint')
                        c.connectAttr(artwork+'.matrixSum',point+'.inMatrix')
                        c.connectAttr(point+'.output',new_shape+'.localPosition')
                    target=new_shape+'.lodVisibility'
                    if incoming:c.connectAttr(incoming,target)
                    else:c.setAttr(target,c.getAttr(plug))
                if incoming:c.disconnectAttr(incoming,plug)
                c.setAttr(plug,lock=False);c.setAttr(plug,False)
            if c.nodeType(source)=='joint':c.setAttr(source+'.drawStyle',2)
            c.addAttr(source,ln='zeroSurface',at='message');c.connectAttr(proxy+'.message',source+'.zeroSurface')
            data=dict(source=source,root=part['root'],role=role,part=key,offsets=offsets,edges=edges,frame=c.currentTime(q=True),artwork_sources=artwork_shapes)
            c.addAttr(proxy,ln='zeroChannelData',dt='string');c.setAttr(proxy+'.zeroChannelData',json.dumps(data),type='string',lock=True)
            mapping[source]=proxy
        part['zero_controls']={r:mapping[n] for r,n in controls.items() if n in mapping};outputs[key]=part['zero_controls']
        c.addAttr(part['root'],ln='zeroPartData',dt='string')
        c.setAttr(part['root']+'.zeroPartData',json.dumps(dict(sources=part['controls'],controls=part['zero_controls'])),type='string',lock=True)
        registry=part['namespace']+':recalculate_node'
        if c.objExists(registry):
            from . import zero_manual
            zero_manual.install()
            c.addAttr(registry,ln='zeroSurfaceLinks',at='message',multi=True)
            for index,control in enumerate(mapping.values()):c.connectAttr(control+'.message',registry+'.zeroSurfaceLinks[%d]'%index)
    rig['zero_channels']=dict(version='1.0.0',frame=c.currentTime(q=True),controls=outputs,nodes=created)
    if 'body' in rig['parts'] and c.objExists(rig['parts']['body']['controls']['hips']+'.bodyDriveData'):
        from .body_zero import enable as enable_body_zero
        rig['parts']['body']['body_drive']=enable_body_zero(rig['parts']['body'])
    from .integrated import display
    display.apply(rig)
    from .arm_ik_shared import enable_pole
    for part in rig['parts'].values():
        if c.objExists(part['root']+'.armWorldIKData'):
            enable_pole(part['root'])
            part['world_ik']=json.loads(c.getAttr(part['root']+'.armWorldIKData'))
    return rig['zero_channels']


def repair_display(rig):
    """Repair v1.21.0 artwork wiring without rebuilding controls or animation."""
    import maya.cmds as c
    from .integrated import display
    repaired=[]
    for part in rig['parts'].values():
        for role,proxy in part.get('zero_controls',{}).items():
            data=json.loads(c.getAttr(proxy+'.zeroChannelData'))
            if 'artwork_sources' in data:continue
            source=data['source']
            originals=c.listRelatives(source,s=True,f=True) or []
            # Original solver curves remain intentionally hidden. The template
            # records exactly which replacement artwork was installed on them.
            template=part.get('appearance',{}).get('controls',{}).get(role,{}).get('shapes',[])
            known=set(c.ls(template,long=True) or []) if template else set()
            artwork=[s for s in originals if s in known or c.objExists(s+'.controllerArtwork')]
            if not artwork:continue
            copies=c.listRelatives(proxy,s=True,f=True) or []
            if len(artwork)!=len(copies):
                raise ValueError('零位控制器外观数量不匹配：'+proxy)
            for src,dst in zip(artwork,copies):
                if c.nodeType(src)!='nurbsCurve' or c.nodeType(dst)!='nurbsCurve':continue
                geometry=c.connectionInfo(dst+'.create',sfd=True).split('.')[0]
                if not geometry or c.nodeType(geometry)!='transformGeometry':continue
                if not c.isConnected(src+'.local',geometry+'.inputGeometry'):
                    c.connectAttr(src+'.local',geometry+'.inputGeometry',force=True)
                    # The mismatched hidden solver shape supplied False here.
                    c.setAttr(dst+'.lodVisibility',True)
                    repaired.append(proxy)
            data['artwork_sources']=artwork
            c.setAttr(proxy+'.zeroChannelData',lock=False)
            c.setAttr(proxy+'.zeroChannelData',json.dumps(data),type='string',lock=True)
    layer=display.apply(rig)
    return dict(repaired=repaired,layer=layer['layer'])


def selected_generic():
    import maya.cmds as c
    result=[]
    for n in c.ls(sl=True,long=True,objectsOnly=True) or []:
        if not c.objExists(n+'.zeroChannelData'):continue
        d=json.loads(c.getAttr(n+'.zeroChannelData'))
        # Existing live-arm gestures and shared wrist IK already isolate input.
        if d['part'].startswith('arm'):
            from . import arm_ik_shared
            if d['role']!='pole_locator' and arm_ik_shared.active(d['root'],d['role']):continue
            if c.objExists(d['root']+'.liveAlignmentData') and d['role'] in ('shoulder_fk','middle_fk','end_fk'):continue
        result.append(n)
    return result


def begin(control):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import live_edit,live_arm_manual
    d=json.loads(c.getAttr(control+'.zeroChannelData'));source=d['source']
    from . import arm_ik_shared
    if d['role']=='pole_locator' and arm_ik_shared.active(d['root'],d['role']):
        return arm_ik_shared.begin(d['root'],role=d['role'])
    if c.objExists(source+'.liveInput'):
        source=(c.listConnections(source+'.liveInput',s=True,d=False) or [source])[0]
    snapshot=live_edit._snapshot([control+'.'+a for a in d['offsets']])
    entry=dict(data={'root':d['root']},role=d['role'],mode=c.contextInfo(c.currentCtx(),c=True),snapshot=snapshot,
               proxy=control,source=source,edges=[],curve_edges=[],changed=False,finished=False,
               generic_zero=True,destinations={},input_basis=om.MMatrix(),native_attrs=TR)
    try:
        display=om.MMatrix(c.xform(control,q=True,ws=True,m=True))
        entry['input_basis']=live_edit._frame(source)*display.inverse()
        for attr in d['offsets']:
            p=control+'.'+attr;dst=source+'.'+attr;edge=c.connectionInfo(dst,sfd=True)
            value=c.getAttr(dst);c.disconnectAttr(edge,dst);c.setAttr(dst,value)
            entry['edges'].append((p,dst));entry.setdefault('input_edges',{})[dst]=edge
            incoming=c.connectionInfo(p,sfd=True)
            if incoming:
                value=c.getAttr(p);c.disconnectAttr(incoming,p);c.setAttr(p,value);entry['curve_edges'].append((incoming,p))
        local=live_arm_manual.neutral_local(control)
        # Locked rotation channels are already neutral on these surfaces.
        for a in TR[3:]:
            if not c.getAttr(control+'.'+a,lock=True):c.setAttr(control+'.'+a,0)
        local.setRotation(om.MEulerRotation());entry['local']=local.asMatrix();entry['parent']=entry['local'].inverse()*display
        entry['display_edge']=c.connectionInfo(control+'.offsetParentMatrix',sfd=True)
        parent=c.listRelatives(control,p=True,f=True)[0]
        entry['native_opm']=entry['parent']*om.MMatrix(c.getAttr(parent+'.worldInverseMatrix[0]'))
        entry['native_start']=[c.getAttr(control+'.'+a) for a in TR];entry['last_native']=list(entry['native_start'])
        if d['part']=='body' and entry['mode']=='manipRotate':
            # Rotating an endpoint bends the spine and naturally moves that
            # endpoint's parent. Do not counteract this motion with translation.
            # Keep explicit translation from a shared/off-center rotate pivot.
            entry['body_rotation_translate']=list(c.getAttr(source+'.translate')[0])
            entry['body_rotation_parent_inverse']=(om.MMatrix(c.getAttr(source+'.offsetParentMatrix'))*om.MMatrix(c.getAttr(source+'.parentMatrix[0]'))).inverse()
        # Source values are intentionally isolated until reconnect; bypass the
        # normal source-to-surface destination lookup while solving this drag.
        entry['destinations']={source+'.'+a:(source if a in d['offsets'] else control)+'.'+a for a in TR}
        live_arm_manual.prepare_native_sample(entry,suspend=False)
        return entry
    except Exception:
        if entry.get('display_edge'):live_arm_manual.restore_display(entry)
        live_arm_manual._reconnect(entry,{p:c.getAttr(dst) for p,dst in entry['edges']})
        live_edit._restore(snapshot);raise
