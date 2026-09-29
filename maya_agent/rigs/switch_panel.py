"""In-scene binary space sliders; animation stays on the original controls.

The displayed end position is DG-driven by the real mode. Handle translateX
is only a transient mouse gesture, never an animation or rig driver.
"""
import json
import math

VERSION='1.3.0'
if '_callbacks' not in globals():_callbacks={}
if '_pending' not in globals():_pending={}
if '_busy' not in globals():_busy=False


def _read(node,attr):
    import maya.cmds as c
    return json.loads(c.getAttr(node+'.'+attr))


def targets(rig):
    """Resolve solver owners, not guessed controller names or the last attr."""
    import maya.cmds as c
    from . import arm_ik
    result={};parts=rig['parts']
    for key,part in parts.items():
        controls=part.get('controls',{})
        candidates=[]
        if key=='body':candidates=[('hips',controls.get('hips')),('chest',controls.get('chest'))]
        elif key=='head':candidates=[('head',controls.get('head'))]
        elif key.startswith('arm_'):
            side=key[-1];candidates=[('wrist_'+side,part['root']),('upper_'+side,controls.get('shoulder_fk'))]
        elif key.startswith('leg_'):
            side=key[-1];candidates=[('foot_'+side,part['root']),('knee_'+side,controls.get('knee'))]
        for role,owner in candidates:
            if owner and c.objExists(owner) and arm_ik._has_mode(owner):
                data=arm_ik._switch_module(owner)._data(owner)
                result[role]=dict(owner=owner,plug=data['global_plug'])
    return result


def _paint(node,color,reference=False):
    import maya.cmds as c
    for shape in c.listRelatives(node,s=True,f=True) or []:
        c.setAttr(shape+'.overrideEnabled',True);c.setAttr(shape+'.overrideRGBColors',True)
        c.setAttr(shape+'.overrideColorRGB',*color)
        # Reference display is a native viewport picking exclusion, unlike
        # locked channels which still allow selecting the decoration.
        c.setAttr(shape+'.overrideDisplayType',2 if reference else 0)
        if c.attributeQuery('lineWidth',node=shape,exists=True):c.setAttr(shape+'.lineWidth',1.7)
    if reference:
        for a in ('tx','ty','tz','rx','ry','rz','sx','sy','sz','v'):c.setAttr(node+'.'+a,lock=True,keyable=False,channelBox=False)


def build(character):
    """Create/reuse one panel for an integrated character without rebinding it."""
    import maya.cmds as c
    from . import arm_ik
    rig=_read(character,'integratedRigData');entries=targets(rig)
    if not entries:raise ValueError('此角色尚未启用可切换的身体驱动或 global。')
    existing=c.listConnections(character+'.spaceSwitchPanel',s=True,d=False) if c.objExists(character+'.spaceSwitchPanel') else []
    if existing and c.objExists(existing[0]+'.spacePanelData'):install();return upgrade(existing[0])
    ns=rig['namespace'];selection=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    nodes=[];root=None;c.undoInfo(openChunk=True,chunkName='CreateSpaceSwitchPanel');c.autoKeyframe(state=False)
    def curve(name,points,parent,reference=True,color=(.92,.92,.92)):
        n=c.curve(name=ns+':'+name,d=1,p=points);nodes.append(n)
        c.parent(n,parent,relative=True);_paint(n,color,reference);return n
    def label(text,x,y,height):
        try:from PySide2 import QtGui
        except ImportError:from PySide6 import QtGui
        font=QtGui.QFont('Microsoft YaHei');font.setPixelSize(100);font.setBold(True)
        path=QtGui.QPainterPath();path.addText(0,0,font,text);bounds=path.boundingRect();scale=height/bounds.height()
        for i,poly in enumerate(path.toSubpathPolygons()):
            points=[(x+(p.x()-bounds.left())*scale,y+(bounds.bottom()-p.y())*scale,0) for p in poly]
            if len(points)>1:curve('switchLabel_'+str(len(nodes))+'_'+str(i),points,root)
    try:
        root=c.createNode('transform',name=ns+':space_switch_panel');nodes.append(root)
        c.parent(root,character,relative=True)
        if rig.get('general_root') and c.objExists(rig['general_root']):
            follow=c.createNode('transform',name=ns+':switchPanelFollow',parent=character);nodes.append(follow)
            nodes.extend(c.parentConstraint(rig['general_root'],follow,maintainOffset=False))
            c.parent(root,follow,relative=True)
        # Character targets give a useful size even when mesh visibility is off.
        sources=[m['target'] for p in rig['parts'].values() for m in p.get('original_target_mapping',[]) if c.objExists(m['target'])]
        if not sources:sources=[n for p in rig['parts'].values() for n in p.get('joints',[]) if c.objExists(n)]
        points=[c.xform(n,q=True,ws=True,t=True) for n in sources]
        lo=[min(p[i] for p in points) for i in range(3)];hi=[max(p[i] for p in points) for i in range(3)]
        height=max(hi[1]-lo[1],20);unit=height*.04
        c.xform(root,ws=True,t=(hi[0]+height*.09,lo[1]+height*.30,(lo[2]+hi[2])*.5))
        c.setAttr(root+'.scale',unit,unit,unit)
        # The newly created panel master also starts with neutral TR channels.
        rest=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.]+list(c.getAttr(root+'.translate')[0])+[1.]
        c.setAttr(root+'.offsetParentMatrix',*rest,type='matrix');c.setAttr(root+'.translate',0,0,0)
        label('R',4.0,13.4,.9);label('L',8.6,13.4,.9)
        sliders={};missing=[]
        rows=[('手','wrist',12),('大臂','upper',9.8),('脚','foot',7.6),('膝盖','knee',5.4),('腰','hips',3.2),('头','head',1)]
        for title,role,y in rows:
            label(title,0,y-.4,.85)
            cells=[(role+'_'+side,x,3.8) for side,x in (('R',2.6),('L',7.2))] if role not in ('hips','head') else [(role,4.1,4.7)]
            for key,x,width in cells:
                enabled=key in entries;color=(.92,.92,.92) if enabled else (.32,.32,.32)
                curve('switchTrack_'+key,[(x,y-.65,0),(x+width,y-.65,0),(x+width,y+.65,0),(x,y+.65,0),(x,y-.65,0)],root,color=color)
                if not enabled:missing.append(key);continue
                base=c.createNode('transform',name=ns+':switchBase_'+key,parent=root);nodes.append(base)
                c.setAttr(base+'.translate',x+.55,y,0)
                display=c.createNode('transform',name=ns+':switchDisplay_'+key,parent=base);nodes.append(display)
                travel=width-1.1
                knob=curve('switch_'+key,[(.39*math.cos(a*math.pi/16),.39*math.sin(a*math.pi/16),.02) for a in range(33)],display,False)
                for a in ('ty','tz','rx','ry','rz','sx','sy','sz','v'):c.setAttr(knob+'.'+a,lock=True,keyable=False,channelBox=False)
                c.setAttr(knob+'.tx',keyable=False,channelBox=True)
                c.transformLimits(knob,tx=(-travel,travel),etx=(True,True))
                mul=c.createNode('multDoubleLinear',name=ns+':switchPosition_'+key);nodes.append(mul)
                source=entries[key];c.connectAttr(source['plug'],mul+'.input1');c.setAttr(mul+'.input2',travel);c.connectAttr(mul+'.output',display+'.tx')
                limits=_limits(knob,display,travel);nodes.extend(limits)
                c.addAttr(knob,ln='global',proxy=source['plug'],keyable=True)
                c.addAttr(knob,ln='switchOwner',at='message');c.connectAttr(source['owner']+'.message',knob+'.switchOwner')
                data=dict(role=key,travel=travel,display=display,owner=source['owner'],plug=source['plug'])
                c.addAttr(knob,ln='spaceSliderData',dt='string');c.setAttr(knob+'.spaceSliderData',json.dumps(data),type='string',lock=True)
                sliders[key]=knob
        data=dict(version=VERSION,root=root,character=character,sliders=sliders,missing=missing,nodes=nodes,column_order=['R','L'])
        c.addAttr(root,ln='spacePanelData',dt='string');c.setAttr(root+'.spacePanelData',json.dumps(data),type='string',lock=True)
        if not c.objExists(character+'.spaceSwitchPanel'):c.addAttr(character,ln='spaceSwitchPanel',at='message')
        c.connectAttr(root+'.message',character+'.spaceSwitchPanel',force=True)
        c.addAttr(root,ln='instructions',dt='string');c.setAttr(root+'.instructions','选择圆形滑块，W 沿横轴拖动；左 0 / 右 1，松开匹配姿态。动画保存在原控制器。',type='string',lock=True)
        data=upgrade(root);arm_ik.install();install();return data
    except Exception:
        for n in reversed(nodes):
            if c.objExists(n):c.delete(n)
        raise
    finally:
        c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(cl=True);c.undoInfo(closeChunk=True)


def upgrade(root):
    """Update layout/picking without replacing sliders, mode links or curves."""
    import maya.cmds as c
    data=_read(root,'spacePanelData');ns=root.rsplit(':',1)[0]
    auto=c.autoKeyframe(q=True,state=True);selection=c.ls(sl=True,long=True) or []
    c.undoInfo(openChunk=True,chunkName='UpdateSpaceSwitchPanel');c.autoKeyframe(state=False)
    try:
        decorations=[n for n in data['nodes'] if c.objExists(n) and any(t in n.rsplit(':',1)[-1] for t in ('switchLabel_','switchTrack_'))]
        if data.get('column_order')!=['R','L']:
            for role in ('wrist','upper','foot','knee'):
                for side,delta in (('L',4.6),('R',-4.6)):
                    for prefix in ('switchTrack_','switchBase_'):
                        n=ns+':'+prefix+role+'_'+side
                        if not c.objExists(n):continue
                        locked=c.getAttr(n+'.tx',lock=True);c.setAttr(n+'.tx',lock=False)
                        c.setAttr(n+'.tx',c.getAttr(n+'.tx')+delta);c.setAttr(n+'.tx',lock=locked)
            for n in decorations:
                if 'switchLabel_' not in n:continue
                xyz=c.xform(n+'.cv[*]',q=True,os=True,t=True)
                if min(xyz[1::3])<13.3:continue
                delta=4.6 if min(xyz[::3])<7 else -4.6
                locked=c.getAttr(n+'.tx',lock=True);c.setAttr(n+'.tx',lock=False)
                c.setAttr(n+'.tx',c.getAttr(n+'.tx')+delta);c.setAttr(n+'.tx',lock=locked)
            data['column_order']=['R','L']
        for n in decorations:
            for shape in c.listRelatives(n,s=True,f=True) or []:
                c.setAttr(shape+'.overrideEnabled',True);c.setAttr(shape+'.overrideDisplayType',2)
        if not data.get('master_control'):
            # Put the selectable shape on the existing panel root: existing
            # transforms/animation and every slider stay in the same hierarchy.
            points=[(-1.25,0),(-.65,.55),(-.65,.25),(.65,.25),(.65,.55),(1.25,0),(.65,-.55),(.65,-.25),(-.65,-.25),(-.65,-.55),(-1.25,0)]
            temp=c.curve(name=ns+':switchPanel_masterShapeSource',d=1,p=[(6.2+x,15.8+y,.02) for x,y in points])
            shape=c.listRelatives(temp,s=True,f=True)[0]
            c.parent(shape,root,shape=True,relative=True);c.delete(temp)
            shape=c.listRelatives(root,s=True,f=True)[-1];shape=c.rename(shape,ns+':switchPanel_masterShape')
            _paint(root,(1,.72,.18),False)
            c.xform(root,os=True,pivots=(6.2,15.8,0),preserve=True)
            data['master_control']=root;data['nodes'].append(shape)
        if not data.get('chest_row'):_add_chest_row(root,data)
        for handle in data['sliders'].values():_key_proxies(handle)
        data['version']=VERSION
        c.setAttr(root+'.spacePanelData',lock=False);c.setAttr(root+'.spacePanelData',json.dumps(data),type='string',lock=True)
        install()
        return data
    finally:
        c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(cl=True);c.undoInfo(closeChunk=True)


def _add_chest_row(root,data):
    """Insert below hips, preserving existing handles, their keys and the master."""
    import maya.cmds as c
    try:from PySide2 import QtGui
    except ImportError:from PySide6 import QtGui
    ns=root.rsplit(':',1)[0];nodes=data['nodes']
    for name in ('switchBase_head','switchTrack_head'):
        n=ns+':'+name
        if c.objExists(n):
            locked=c.getAttr(n+'.ty',lock=True);c.setAttr(n+'.ty',lock=False)
            c.setAttr(n+'.ty',c.getAttr(n+'.ty')-2.2);c.setAttr(n+'.ty',lock=locked)
    for n in list(nodes):
        if not c.objExists(n) or 'switchLabel_' not in n:continue
        points=c.xform(n+'.cv[*]',q=True,os=True,t=True)
        if points and max(points[::3])<2.5 and min(points[1::3])>=.59 and max(points[1::3])<1.6:
            c.setAttr(n+'.ty',lock=False);c.setAttr(n+'.ty',c.getAttr(n+'.ty')-2.2);c.setAttr(n+'.ty',lock=True)
    def curve(name,points,parent,reference=True,color=(.92,.92,.92)):
        n=c.curve(name=ns+':'+name,d=1,p=points);nodes.append(n)
        c.parent(n,parent,relative=True);_paint(n,color,reference);return n
    font=QtGui.QFont('Microsoft YaHei');font.setPixelSize(100);font.setBold(True)
    path=QtGui.QPainterPath();path.addText(0,0,font,'胸');bounds=path.boundingRect();scale=.85/bounds.height()
    for i,poly in enumerate(path.toSubpathPolygons()):
        points=[((p.x()-bounds.left())*scale,.6+(bounds.bottom()-p.y())*scale,0) for p in poly]
        if len(points)>1:curve('switchLabel_chest_'+str(i),points,root)
    source=targets(_read(data['character'],'integratedRigData')).get('chest')
    curve('switchTrack_chest',[(4.1,.35,0),(8.8,.35,0),(8.8,1.65,0),(4.1,1.65,0),(4.1,.35,0)],root,
          color=(.92,.92,.92) if source else (.32,.32,.32))
    if source:
        base=c.createNode('transform',name=ns+':switchBase_chest',parent=root);nodes.append(base);c.setAttr(base+'.translate',4.65,1,0)
        display=c.createNode('transform',name=ns+':switchDisplay_chest',parent=base);nodes.append(display)
        knob=curve('switch_chest',[(.39*math.cos(a*math.pi/16),.39*math.sin(a*math.pi/16),.02) for a in range(33)],display,False)
        for a in ('ty','tz','rx','ry','rz','sx','sy','sz','v'):c.setAttr(knob+'.'+a,lock=True,keyable=False,channelBox=False)
        c.setAttr(knob+'.tx',keyable=False);c.transformLimits(knob,tx=(-3.6,3.6),etx=(True,True))
        mul=c.createNode('multDoubleLinear',name=ns+':switchPosition_chest');nodes.append(mul)
        c.connectAttr(source['plug'],mul+'.input1');c.setAttr(mul+'.input2',3.6);c.connectAttr(mul+'.output',display+'.tx')
        nodes.extend(_limits(knob,display,3.6))
        c.addAttr(knob,ln='global',proxy=source['plug'],keyable=True)
        c.addAttr(knob,ln='switchOwner',at='message');c.connectAttr(source['owner']+'.message',knob+'.switchOwner')
        entry=dict(role='chest',travel=3.6,display=display,owner=source['owner'],plug=source['plug'])
        c.addAttr(knob,ln='spaceSliderData',dt='string');c.setAttr(knob+'.spaceSliderData',json.dumps(entry),type='string',lock=True)
        data['sliders']['chest']=knob
    elif 'chest' not in data['missing']:data['missing'].append('chest')
    data['chest_row']=True


def _key_proxies(handle):
    """Native S/setKeyframe routes to every editable animator channel.

    Proxies avoid key-edit callbacks, duplicate curves and global hotkey changes.
    The slider's own transient translation remains non-keyable.
    """
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import arm_ik,live_layers
    data=_read(handle,'spaceSliderData');owner=(c.listConnections(handle+'.switchOwner',s=True,d=False) or [data['owner']])[0]
    mode=arm_ik._switch_module(owner)._data(owner)
    control=mode.get('control') or mode.get('fk_wrist') or mode['controls'][0]
    from .zero_channels import surface
    control=surface(control)
    attrs=c.listAttr(control,keyable=True,unlocked=True,scalar=True) or []
    registered=live_layers.blend_nodes();proxies={}
    for attr in attrs:
        if attr in ('global','bodyDrive'):continue
        source=control+'.'+attr
        if c.getAttr(source,type=True) not in ('double','doubleAngle','doubleLinear','float','long','short','byte','bool','enum','time'):continue
        # Live controls already expose proxy channels (IK TR, stretch, etc.).
        # Resolve those links before checking for actual external rig drivers.
        seen=set()
        while source not in seen:
            seen.add(source);selection=om.MSelectionList();selection.add(source)
            if not om.MFnAttribute(selection.getPlug(0).attribute()).isProxyAttribute:break
            upstream=c.connectionInfo(source,sfd=True)
            if not upstream:break
            source=upstream
        try:live_layers.curves_for_plug(source,registered)
        except ValueError:continue
        proxy=handle+'.control_'+attr
        if not c.objExists(proxy):c.addAttr(handle,ln='control_'+attr,nn=c.attributeQuery(attr,node=control,niceName=True),proxy=source,keyable=True)
        proxies[proxy]=source
    c.setAttr(handle+'.tx',keyable=False,channelBox=False)
    data.update(key_control=control,key_proxies=proxies)
    c.setAttr(handle+'.spaceSliderData',lock=False);c.setAttr(handle+'.spaceSliderData',json.dumps(data),type='string',lock=True)
    return proxies


def apply(handle,value,key=None):
    """Same matcher and keying policy as editing the original mode channel."""
    import maya.cmds as c
    from . import arm_ik
    data=_read(handle,'spaceSliderData');owners=c.listConnections(handle+'.switchOwner',s=True,d=False) or []
    if not owners:raise ValueError('滑块对应的控制器已删除。')
    owner=owners[0]
    return arm_ik._switch_module(owner).switch(owner,int(value),key=key)


def _limits(handle,display,travel):
    """Keep the knob inside its track, even when playback changes the mode."""
    import maya.cmds as c
    lower=c.createNode('multDoubleLinear',name=handle+'_min')
    upper=c.createNode('addDoubleLinear',name=handle+'_max')
    c.connectAttr(display+'.tx',lower+'.input1');c.setAttr(lower+'.input2',-1)
    c.connectAttr(lower+'.output',handle+'.minTransXLimit')
    c.connectAttr(lower+'.output',upper+'.input1');c.setAttr(upper+'.input2',travel)
    c.connectAttr(upper+'.output',handle+'.maxTransXLimit')
    return [lower,upper]


def _finish(handle):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    global _busy
    pending=_pending.get(handle)
    if not pending:return
    try:
        try:from PySide2 import QtCore,QtWidgets
        except ImportError:from PySide6 import QtCore,QtWidgets
        if QtWidgets.QApplication.mouseButtons()!=QtCore.Qt.NoButton:
            QtCore.QTimer.singleShot(30,lambda:_finish(handle));return
        _pending.pop(handle,None);_busy=True
        if c.objExists(handle) and not om.MGlobal.isUndoing() and not om.MGlobal.isRedoing():
            data=_read(handle,'spaceSliderData')
            value=c.getAttr(data['display']+'.tx')+c.getAttr(handle+'.tx')
            c.setAttr(handle+'.tx',0)
            if c.currentTime(q=True)==pending['time']:apply(handle,value>=data['travel']*.5,key=pending['auto'])
    except Exception as exc:c.warning('模式面板：'+str(exc))
    finally:
        if handle not in _pending:
            _busy=False;c.undoInfo(closeChunk=True)


def install():
    """Reinstall on plugin startup and scene open/import via arm_ik.install."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    if c.about(batch=True):return 0
    for n,entry in list(_callbacks.items()):
        if not c.objExists(n+'.spaceSliderData') or not entry['handle'].isValid() or not entry['handle'].isAlive():
            try:om.MMessage.removeCallback(entry['id'])
            except RuntimeError:pass
            _callbacks.pop(n,None)
    handles=c.ls('*.spaceSliderData','*:*.spaceSliderData',objectsOnly=True) or []
    for n in handles:
        if n in _callbacks:continue
        sl=om.MSelectionList();sl.add(n);obj=sl.getDependNode(0)
        def changed(msg,plug,other,client,n=n):
            if _busy or not msg&om.MNodeMessage.kAttributeSet or plug.partialName(useLongNames=True) not in ('translateX','translate'):return
            if om.MGlobal.isUndoing() or om.MGlobal.isRedoing() or oma.MAnimControl.isPlaying() or oma.MAnimControl.isScrubbing():return
            if n in _pending or abs(c.getAttr(n+'.tx'))<1e-8:return
            import functools,maya.utils
            c.undoInfo(openChunk=True,chunkName='SwitchPanelMode')
            _pending[n]=dict(time=c.currentTime(q=True),auto=c.autoKeyframe(q=True,state=True))
            maya.utils.executeDeferred(functools.partial(_finish,n))
        _callbacks[n]=dict(id=om.MNodeMessage.addAttributeChangedCallback(obj,changed),handle=om.MObjectHandle(obj))
    return len(_callbacks)


def build_selected():
    import maya.cmds as c
    roots=c.ls('*.integratedRigData','*:*.integratedRigData',objectsOnly=True) or []
    selection=c.ls(sl=True,long=True) or []
    candidates=[r for r in roots if any(r in (c.ls(n,long=True) or [''])[0] or n.rsplit('|',1)[-1].startswith(r.rsplit(':',1)[0]+'_') for n in selection)]
    if len(candidates)==1:return build(candidates[0])
    if len(roots)==1:return build(roots[0])
    raise ValueError('请先创建集成绑定；有多个角色时，请选中目标角色的绑定组或控制器。')
