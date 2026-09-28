"""Interaction-time input alignment for the live limb control surfaces.

The display graph must never be mistaken for the input coordinate system.
Before a native transform gesture, align the original input chain to the
already-solved pose. Playback remains entirely in the dependency graph.
"""
import json

TR = tuple(p+a for p in ('translate', 'rotate') for a in 'XYZ')


class PosePreservationError(RuntimeError):
    """Alignment was rejected and its input snapshot has been restored."""
    def __init__(self,root,error,snapshot):
        self.root=root;self.error=error;self.snapshot=snapshot
        super().__init__('实时输入校准未能保留姿态，已回退：'+root+' '+str(error))


def _set(plug,value):
    import maya.cmds as c
    c.setAttr(plug,value)


def _frame(node):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    m = om.MTransformationMatrix()
    m.setTranslation(om.MVector(c.getAttr(node+'.rotatePivot')[0]), om.MSpace.kTransform)
    return m.asMatrix()*om.MMatrix(c.xform(node, q=True, ws=True, m=True))


def _world(node, desired, destinations):
    """Solve rotation and pivot translation in the original input parent space."""
    import math
    import maya.cmds as c
    import maya.api.OpenMaya as om
    if c.objExists(node+'.liveRotationData'):
        from .live_rotation import solve_rotation
        proxy=destinations[node+'.rotateX'].rsplit('.',1)[0]
        parent=solve_rotation(node,desired,proxy)
        actual=list(_frame(node))[12:15]
        delta=om.MVector(*[desired[12+i]-actual[i] for i in range(3)])*parent.inverse()
        for axis,value in zip('XYZ',delta):
            plug=destinations.get(node+'.translate'+axis,node+'.translate'+axis)
            if not c.getAttr(plug,lock=True) and abs(value)>1e-9:_set(plug,c.getAttr(plug)+value)
        return
    parent = om.MMatrix(c.getAttr(node+'.parentMatrix[0]'))
    parent = om.MMatrix(c.getAttr(node+'.offsetParentMatrix'))*parent
    local = desired*parent.inverse()
    rotation = om.MTransformationMatrix(local).rotation(asQuaternion=True).asMatrix()
    def orientation(attr):
        return om.MEulerRotation(*[math.radians(v) for v in c.getAttr(node+'.'+attr)[0]]).asMatrix()
    rotation = orientation('rotateAxis').inverse()*rotation
    if c.nodeType(node)=='joint': rotation *= orientation('jointOrient').inverse()
    order = c.getAttr(node+'.rotateOrder')
    euler = om.MTransformationMatrix(rotation).rotation(asQuaternion=True).asEulerRotation()
    euler.reorderIt(order)
    previous = om.MEulerRotation(*[math.radians(v) for v in c.getAttr(node+'.rotate')[0]], order)
    euler = euler.closestSolution(previous)
    for axis, value in zip('XYZ', euler):
        plug = destinations.get(node+'.rotate'+axis, node+'.rotate'+axis)
        if not c.getAttr(plug, lock=True) and abs(c.getAttr(plug)-math.degrees(value))>1e-9:
            _set(plug, math.degrees(value))
    # Maya's xform -rp query returns the origin for joints with nonzero pivots.
    actual = list(_frame(node))[12:15]
    delta = om.MVector(*[desired[12+i]-actual[i] for i in range(3)])*parent.inverse()
    for axis, value in zip('XYZ', delta):
        plug = destinations.get(node+'.translate'+axis, node+'.translate'+axis)
        if not c.getAttr(plug, lock=True) and abs(value)>1e-9:
            _set(plug, c.getAttr(plug)+value)


def _plan(root):
    """Match inputs to the current solved pose without invoking Easy Rig or keying."""
    import maya.cmds as c
    data = json.loads(c.getAttr(root+'.liveAlignmentData'))
    destinations = {e['source']:e['proxy'] for e in data['entries']}
    ns = root.rsplit('|',1)[-1].rsplit(':', 1)[0]
    side = 'R' if '_R' in data['inputs'][next(iter(data['inputs']))].rsplit(':',1)[-1] else 'L'
    if data['kind']=='arm':
        pole = ns+':elb_'+side+'1'
        frames = [(data['inputs'][role], _frame(data['targets'][role]))
                  for role in ('shoulder_fk', 'middle_fk', 'end_fk')]
        frames.append((pole, _frame(pole)))
        zero = [ns+':hand_'+side+'1']
        restore = []
    else:
        toe = ns+':toe_'+side+'1'
        knee = ns+':Knee_'+side
        # Toe display includes the ball's motion while the original toe input
        # remains its sibling. Retain that visible pivot when absorbing roll.
        toe_frame=data['controls'].get('toe',toe)
        restore = [(knee, _frame(knee)),(toe, _frame(toe_frame))]
        frames = [(data['inputs']['foot'], _frame(data['targets']['foot']))]
        zero = [ns+':'+name+'_'+side+'1' for name in ('ik_connect','tarsus','heel','toe_end')]
    return data, destinations, frames, zero, restore


def _snapshot(plugs):
    import maya.cmds as c
    from .live_layers import blend_nodes,curves_for_plug
    values={p:c.getAttr(p) for p in plugs if not c.getAttr(p,lock=True)}
    curves={}
    registered=blend_nodes();nodes=set()
    for p in values:
        nodes.update(curves_for_plug(p,registered))
    for node in nodes:
        curves[node]=dict(times=c.keyframe(node,q=True,tc=True),values=c.keyframe(node,q=True,vc=True),
                          itt=c.keyTangent(node,q=True,itt=True),ott=c.keyTangent(node,q=True,ott=True))
        for flag in ('ia','oa','iw','ow','lock','weightLock'):
            curves[node][flag]=c.keyTangent(node,q=True,**{flag:True})
        curves[node]['weighted']=c.keyTangent(node,q=True,weightedTangents=True)[0]
    return values,curves


def _restore(snapshot):
    import maya.cmds as c
    values,curves=snapshot
    for plug,value in values.items():
        if not c.connectionInfo(plug,sourceFromDestination=True):c.setAttr(plug,value)
    for node,data in curves.items():
        old=set(data['times'])
        for t in c.keyframe(node,q=True,tc=True) or []:
            if t not in old:c.cutKey(node,time=(t,t),clear=True)
        changed=c.keyframe(node,q=True,vc=True)!=data['values']
        if not changed:continue
        for i,v in enumerate(data['values']):c.keyframe(node,e=True,index=(i,i),vc=v)
        for i,(itt,ott) in enumerate(zip(data['itt'],data['ott'])):
            c.keyTangent(node,e=True,index=(i,i),lock=False)
            if data['weighted']:c.keyTangent(node,e=True,index=(i,i),weightLock=False)
            c.keyTangent(node,e=True,index=(i,i),**{flag:data[flag][i] for flag in ('ia','oa','iw','ow')})
            c.keyTangent(node,e=True,index=(i,i),itt=itt,ott=ott,lock=data['lock'][i])
            if data['weighted']:c.keyTangent(node,e=True,index=(i,i),weightLock=data['weightLock'][i])
    c.dgdirty(list(curves)+list({p.split('.')[0] for p in values}))
    # Native moves with Auto Key off are unevaluated channel overrides, not
    # curve edits. Restore these after dirtying, or a mere click loses the pose.
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    try:
        for plug,value in values.items():c.setAttr(plug,value)
    finally:c.autoKeyframe(state=auto)


def prepare(root, wrist_only=False):
    """Rebase the editable inputs. No keyframe creation or playback callback.

This is part of an editing gesture. Curves are temporarily disconnected while
solving and reconnected unchanged; calibrated values remain native unkeyed
overrides. Never call on load, selection, time change or metadata upgrade.
"""
    import maya.cmds as c
    data,destinations,frames,zero,restore=_plan(root)
    if wrist_only and data['kind']=='arm':
        # Wrist rotation has no reason to reparameterize the shoulder, elbow or
        # pole. Equal endpoint poses in different FK bases interpolate unequally.
        frames=[item for item in frames if item[0]==data['inputs']['end_fk']]
    nodes=list(dict.fromkeys([n for n,m in frames+restore]+zero))
    plugs=[destinations.get(n+'.'+a,n+'.'+a) for n in nodes for a in TR]
    snapshot=_snapshot(plugs)
    # The solved output, not the moved input hierarchy, is the preservation test.
    ns=root.rsplit('|',1)[-1].rsplit(':',1)[0]
    joints=[ns+':joint'+str(i) for i in range(1,4 if data['kind']=='arm' else 5)]
    baseline={n:c.xform(n,q=True,ws=True,m=True) for n in joints}
    edges={p:c.connectionInfo(p,sourceFromDestination=True) for p in snapshot[0]}
    edges={p:s for p,s in edges.items() if s}
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    try:
        for plug,source in edges.items():
            c.disconnectAttr(source,plug);c.setAttr(plug,snapshot[0][plug])
        endpoint=(data['targets']['foot'],frames[0][1]) if data['kind']=='leg' else None
        _apply_plan(destinations,frames,zero,restore,endpoint)
        edited={p:c.getAttr(p) for p in edges}
        for plug,source in edges.items():c.connectAttr(source,plug)
        for plug,value in edited.items():_set(plug,value)
        error=max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise PosePreservationError(root,error,snapshot)
    except Exception:
        for plug,source in edges.items():
            if not c.isConnected(source,plug):c.connectAttr(source,plug)
        _restore(snapshot)
        raise
    finally:c.autoKeyframe(state=auto)
    return snapshot


def _apply_plan(destinations,frames,zero,restore,endpoint=None):
    import maya.cmds as c
    for node, matrix in frames:
        _world(node, matrix, destinations)
    for node in zero:
        for attr in TR:
            plug = destinations.get(node+'.'+attr, node+'.'+attr)
            if not c.getAttr(plug, lock=True) and abs(c.getAttr(plug))>1e-9:
                _set(plug, 0)
    if endpoint:
        for node in zero:
            # Pivot compensation is a frozen animation reference. Cancel its
            # current offset in editable translation so every reverse-foot
            # input pivot shares the displayed final-foot coordinate frame.
            matrix=c.getAttr(node+'.matrix')
            for i,axis in enumerate('XYZ'):
                plug=destinations.get(node+'.translate'+axis,node+'.translate'+axis)
                if not c.getAttr(plug,lock=True) and abs(matrix[12+i])>1e-9:
                    _set(plug,c.getAttr(plug)-matrix[12+i])
        # Animated pivot compensation can leave a residual local translation
        # after zeroing roll channels. Solve the foot input against the actual
        # endpoint frame, retaining the frozen compensation graph unchanged.
        end,desired=endpoint
        foot=frames[0][0]
        _world(foot,_frame(foot)*_frame(end).inverse()*desired,destinations)
    for node, matrix in restore:
        _world(node, matrix, destinations)


# Preserve callback ownership across installer importlib.reload calls.
if '_gesture' not in globals():_gesture=None
if '_undo_payloads' not in globals():_undo_payloads={}


def _fence(phase,snapshots):
    import uuid
    import maya.cmds as c
    token=uuid.uuid4().hex
    _undo_payloads[token]=(phase,snapshots)
    try:c.mayaLiveEditState(token)
    finally:_undo_payloads.pop(token,None)


def _roots():
    import maya.cmds as c
    roots=[]
    for selected in c.ls(sl=True,long=True,objectsOnly=True) or []:
        if not c.objExists(selected+'.liveInput'):continue
        node=selected
        while node:
            if c.objExists(node+'.liveAlignmentData'):
                if c.getAttr(node+'.liveAlignment'):roots.append(node)
                break
            parent=c.listRelatives(node,p=True,fullPath=True) or []
            node=parent[0] if parent else None
    return list(dict.fromkeys(roots))


def before_drag(context):
    import maya.cmds as c
    global _gesture
    roots=_roots()
    if not roots:return
    if _gesture:after_drag(context)
    c.undoInfo(openChunk=True,chunkName='LiveLimbTransform')
    _gesture={'snapshots':[],'prepared':{},'auto':c.autoKeyframe(q=True,state=True),'rotation_layers':[], 'arm_gestures':[]}
    try:
        from . import live_arm_manual
        from .live_layers import edit_layer
        _gesture['anim_layer']=edit_layer(roots)
        if _gesture['anim_layer']:c.autoKeyframe(state=False)
        _fence('before',_gesture['snapshots'])
        for root in roots:
            arm_roles=live_arm_manual.selected_roles(root)
            if arm_roles:
                c.autoKeyframe(state=False)
                entry=live_arm_manual.begin_many(root,arm_roles)
                snapshot=entry['snapshot'];_gesture['arm_gestures'].append(entry)
                _gesture['snapshots'].append(snapshot)
                _gesture['prepared'].update(snapshot[0])
                continue
            snapshot=prepare(root)
            _gesture['snapshots'].append(snapshot)
            _gesture['prepared'].update({p:c.getAttr(p) for p in snapshot[0]})
        # Auto Key is suspended during live input isolation. Include ordinary
        # co-selected controls so mixed selections retain Maya's key behavior.
        native_plugs=[]
        for node in c.ls(sl=True,long=True,objectsOnly=True) or []:
            for attr in TR:
                plug=node+'.'+attr
                if not c.objExists(plug) or not c.getAttr(plug,keyable=True) or c.getAttr(plug,lock=True):continue
                short=node.rsplit('|',1)[-1]+'.'+attr
                if plug in _gesture['prepared'] or short in _gesture['prepared']:continue
                incoming=c.connectionInfo(plug,sourceFromDestination=True)
                if not incoming or c.nodeType(incoming.split('.')[0]).startswith(('animCurve','animBlendNode')):native_plugs.append(plug)
        if native_plugs:
            snapshot=_snapshot(native_plugs);_gesture['snapshots'].append(snapshot)
            _gesture['prepared'].update(snapshot[0])
    except Exception:
        from .live_arm_manual import finish
        for entry in reversed(_gesture['arm_gestures']):finish(entry,cancel=True)
        from .live_rotation import rollback
        for entry in reversed(_gesture['rotation_layers']):rollback(entry)
        for snapshot in reversed(_gesture['snapshots']):_restore(snapshot)
        c.autoKeyframe(state=_gesture['auto']);_gesture=None;c.undoInfo(closeChunk=True)
        raise


def update_drag(force=False):
    if not _gesture:return
    from .live_arm_manual import update,restore_display
    entries=_gesture.get('arm_gestures',[])
    try:
        for entry in entries:update(entry,force=force)
    finally:
        for entry in entries:restore_display(entry)


def _native_move_update(gesture):
    if _gesture is not gesture or gesture.get('ending'):return
    gesture['update_pending']=False
    update_drag(force=True)


def _native_end_update(gesture):
    if _gesture is gesture:after_drag('viewport')


def _wrist_rotation(root):
    return _isolated_arm_rotation(root)=='end_fk'


def _isolated_arm_rotation(root):
    """Only an isolated wrist rotation can use the local input calibration."""
    import maya.cmds as c
    if c.contextInfo(c.currentCtx(),c=True)!='manipRotate':return None
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    if data['kind']!='arm':return None
    full=c.ls(root,long=True)[0]
    selected=[n for n in c.ls(sl=True,long=True,objectsOnly=True) or [] if n.startswith(full+'|')]
    for role,proxy in data['controls'].items():
        if selected==c.ls(proxy,long=True):return role
    return None


def after_drag(context):
    import maya.cmds as c
    global _gesture
    try:
        if _gesture:
            from .live_arm_manual import finish
            for entry in _gesture.get('arm_gestures',[]):finish(entry)
            # A click without a drag must not change animation or reset roll.
            changed=any(abs(c.getAttr(p)-v)>1e-8 for p,v in _gesture['prepared'].items() if c.objExists(p))
            if not changed:
                from .live_rotation import rollback
                for entry in reversed(_gesture['rotation_layers']):rollback(entry)
                for snapshot in reversed(_gesture['snapshots']):_restore(snapshot)
            else:
                from .live_rotation import finish
                auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
                try:
                    for entry in _gesture['rotation_layers']:
                        finish(entry,entry['snapshot'],_gesture['auto'])
                finally:c.autoKeyframe(state=auto)
            if changed and _gesture.get('anim_layer'):
                from .live_layers import commit
                commit(_gesture['anim_layer'],_gesture['snapshots'],_gesture['auto'])
            elif changed and _gesture['auto']:
                # Include the companion channels rebased before the native drag.
                # Otherwise Maya keys only the selected proxy and loses the
                # calibrated pose when the animator returns to this frame.
                committed={p:c.getAttr(p) for values,curves in _gesture['snapshots'] for p in values} if _gesture.get('arm_gestures') else {}
                arm_plugs={p for entry in _gesture.get('arm_gestures',[]) for p in entry['snapshot'][0]}
                for values,curves in _gesture['snapshots']:
                    for plug,old in values.items():
                        value=committed[plug] if plug in committed else c.getAttr(plug)
                        if abs(value-old)<1e-9:continue
                        incoming=c.connectionInfo(plug,sourceFromDestination=True)
                        if not incoming and curves and plug in arm_plugs:
                            for t in sorted({t for curve in curves.values() for t in curve['times']}):
                                c.setKeyframe(plug,time=t,value=old)
                            c.setAttr(plug,value)
                            incoming=c.connectionInfo(plug,sourceFromDestination=True)
                        if incoming and curves and c.nodeType(incoming.split('.')[0]).startswith('animCurve'):
                            c.setKeyframe(plug,time=c.currentTime(q=True),value=value)
                for plug,value in committed.items():c.setAttr(plug,value)
            _fence('after',[_snapshot(values) for values,curves in _gesture['snapshots']])
    except Exception:
        # One failed arm must not leave the other selected arms disconnected.
        if _gesture:
            from .live_arm_manual import finish
            for entry in reversed(_gesture.get('arm_gestures',[])):finish(entry,cancel=True)
            for snapshot in reversed(_gesture['snapshots']):_restore(snapshot)
        raise
    finally:
        if _gesture:
            c.autoKeyframe(state=_gesture['auto']);c.undoInfo(closeChunk=True)
        _gesture=None


def install():
    """Attach before Maya caches a mouse-down transform; never intercept playback.

    Native context preDragCommand callbacks do not fire for ordinary transform
    controls on Maya 2024. A non-consuming viewport event filter runs before the
    native manipulator reads the starting channels. Release cleanup is deferred
    until Maya has committed its own undo command.
    """
    import maya.cmds as c
    if c.about(batch=True):return False
    # Migrate only sessions carrying our obsolete experimental context hooks.
    # Empty Python callbacks are not equivalent to clearing a MEL context hook.
    if globals().pop('_hooks',None) is not None:
        import maya.mel as mel
        for context,command in (('Move','manipMoveContext'),('Rotate','manipRotateContext')):
            for flag in ('preDragCommand','postDragCommand'):
                for typ in ('transform','joint','nurbsCurve'):
                    mel.eval(command+' -edit -'+flag+' "" "'+typ+'" '+context+';')
    from pathlib import Path
    plugin=str(Path(__file__).with_name('maya_live_edit_undo.py'))
    if not c.pluginInfo('maya_live_edit_undo.py',q=True,loaded=True):c.loadPlugin(plugin,quiet=True)
    try:
        from PySide2 import QtCore,QtWidgets
        from shiboken2 import getCppPointer
    except ImportError:
        from PySide6 import QtCore,QtWidgets
        from shiboken6 import getCppPointer
    import maya.api.OpenMayaUI as ui
    global _filter
    if globals().get('_filter') is not None:
        if globals().get('_filter_version')==6:return True
        QtWidgets.QApplication.instance().removeEventFilter(_filter)
        _filter.deleteLater();_filter=None
    class Filter(QtCore.QObject):
        def eventFilter(self,watched,event):
            if getattr(self,'dispatching',False):return False
            kind=event.type()
            if kind==QtCore.QEvent.MouseMove and _gesture and _gesture.get('arm_gestures') and event.buttons() & (QtCore.Qt.LeftButton|QtCore.Qt.MiddleButton):
                if not _gesture.get('ending'):
                    from .live_arm_manual import prepare_native_sample
                    for entry in _gesture['arm_gestures']:prepare_native_sample(entry)
                    # Finish the solve in this mouse event. A timer permits
                    # Maya to paint the temporary input handle before the
                    # bone-follow display is restored, causing a visible twitch.
                    self.dispatching=True
                    try:QtWidgets.QApplication.sendEvent(watched,event)
                    finally:
                        self.dispatching=False
                        update_drag(force=True)
                    return True
            if kind in (QtCore.QEvent.MouseButtonRelease,QtCore.QEvent.ApplicationDeactivate) and _gesture:
                if _gesture.get('arm_gestures'):
                    if not _gesture.get('ending'):
                        gesture=_gesture;gesture['ending']=True
                        QtCore.QTimer.singleShot(0,lambda:_native_end_update(gesture))
                else:QtCore.QTimer.singleShot(0,lambda:after_drag('viewport'))
            if kind!=QtCore.QEvent.MouseButtonPress or event.button() not in (QtCore.Qt.LeftButton,QtCore.Qt.MiddleButton):
                return False
            if not isinstance(watched,QtWidgets.QWidget):return False
            if event.modifiers() & QtCore.Qt.AltModifier:return False
            if c.contextInfo(c.currentCtx(),c=True) not in ('manipMove','manipRotate'):return False
            if not _roots():return False
            pointers=set()
            for panel in c.getPanel(type='modelPanel') or []:
                try:pointers.add(int(ui.M3dView.getM3dViewFromModelPanel(panel).widget()))
                except RuntimeError:pass
            widget=watched
            while widget and int(getCppPointer(widget)[0]) not in pointers:widget=widget.parentWidget()
            if not widget:return False
            try:before_drag('viewport')
            except Exception as exc:
                c.warning(str(exc))
                # Do not allow the bad gesture to proceed on an uncalibrated rig.
                return True
            return False
    _filter=Filter(QtWidgets.QApplication.instance())
    globals()['_filter_version']=6
    QtWidgets.QApplication.instance().installEventFilter(_filter)
    return True
