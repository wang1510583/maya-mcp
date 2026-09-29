"""Native time-slider tick colors for wrist and foot space modes.

Only keyTickDrawSpecial is edited. Curves, breakdown status and animation
values are unchanged. Loaded by the rig runtime; global=1 uses special ticks.
"""
import json

if '_callbacks' not in globals():_callbacks=[]
if '_roots' not in globals():_roots=[]
if '_queued' not in globals():_queued=False
if '_busy' not in globals():_busy=False
if '_generation' not in globals():_generation=0


def _data(root):
    import maya.cmds as c
    if c.objExists(root+'.armWorldIKData'):
        data=json.loads(c.getAttr(root+'.armWorldIKData'))
        return dict(control=data['fk_wrist'],global_plug=data['global_plug'],
                    extra=[data['controls']['wrist']+'.'+a for a in ('translateX','translateY','translateZ','rotateX','rotateY','rotateZ')])
    if c.objExists(root+'.footSpaceData'):
        data=json.loads(c.getAttr(root+'.footSpaceData'))
        return dict(control=data['control'],global_plug=data['global_plug'],extra=[])
    return None


def _curves(data):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import live_layers
    registered=live_layers.blend_nodes();curves=set()
    wrist=data['control']
    for attr in c.listAttr(wrist,keyable=True,scalar=True) or []:
        p=wrist+'.'+attr
        sel=om.MSelectionList();sel.add(p)
        if om.MFnAttribute(sel.getPlug(0).attribute()).isProxyAttribute:
            p=c.connectionInfo(p,sfd=True) or p
        try:curves.update(live_layers.curves_for_plug(p,registered))
        except ValueError:continue
    # Include the source mode and IK channels explicitly: Maya versions differ
    # in how proxy attributes participate in keyframe/connection queries.
    for p in [data['global_plug']]+data['extra']:
        curves.update(live_layers.curves_for_plug(p,registered))
    return curves


def refresh():
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    from . import arm_ik,live_layers
    global _busy
    if _busy or arm_ik._busy or arm_ik._pending or om.MGlobal.isUndoing() or om.MGlobal.isRedoing() or oma.MAnimControl.isPlaying():return []
    _busy=True;undo=c.undoInfo(q=True,state=True);reports=[]
    try:
        # Cosmetic refreshes must not become a separate animation Undo step.
        c.undoInfo(stateWithoutFlush=False)
        for root in _roots:
            data=_data(root)
            if not data:continue
            curves=_curves(data)
            keyed_mode=bool(live_layers.curves_for_plug(data['global_plug']))
            static=c.getAttr(data['global_plug']);modes={};changed=0;special=[]
            for curve in sorted(curves):
                for i,t in enumerate(c.keyframe(curve,q=True,tc=True) or []):
                    if t not in modes:modes[t]=int((c.getAttr(data['global_plug'],time=t) if keyed_mode else static)>=.5)
                    value=bool(modes[t])
                    if bool(c.getAttr(curve+'.keyTickDrawSpecial[%d]'%i))!=value:
                        c.keyframe(curve,e=True,index=(i,i),tickDrawSpecial=value);changed+=1
                    if value:special.append(t)
            reports.append(dict(control=data['control'],changed=changed,green_frames=sorted(set(special)),normal_frames=sorted(t for t,v in modes.items() if not v)))
        return reports
    finally:
        c.undoInfo(stateWithoutFlush=undo);_busy=False


def _run(generation):
    global _queued
    if generation!=_generation:return
    _queued=False
    refresh()


def _request(*args):
    global _queued
    if _busy or _queued:return
    from PySide2 import QtCore
    _queued=True;generation=_generation
    QtCore.QTimer.singleShot(100,lambda:_run(generation))


def uninstall():
    """Stop automatic coloring; leave existing native display flags intact."""
    import maya.api.OpenMaya as om
    global _queued,_generation
    _generation+=1;_queued=False
    for callback in _callbacks:
        try:om.MMessage.removeCallback(callback)
        except RuntimeError:pass
    _callbacks[:]=[];_roots[:]=[]


def install(roots=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    uninstall()
    _roots[:]=list(roots) if roots is not None else [n for n in c.ls('*:rig_root') or [] if _data(n)]
    _callbacks.append(oma.MAnimMessage.addAnimCurveEditedCallback(_request))
    for event in ('SelectionChanged','Undo','Redo','timeChanged'):
        _callbacks.append(om.MEventMessage.addEventCallback(event,_request))
    for root in _roots:
        data=_data(root)
        if not data:continue
        node,attr=data['global_plug'].rsplit('.',1)
        sel=om.MSelectionList();sel.add(node)
        def changed(msg,plug,other,client,attr=attr):
            if msg&om.MNodeMessage.kAttributeSet and plug.partialName(useLongNames=True)==attr:_request()
        _callbacks.append(om.MNodeMessage.addAttributeChangedCallback(sel.getDependNode(0),changed))
    _callbacks.append(om.MSceneMessage.addCallback(om.MSceneMessage.kBeforeNew,lambda *a:uninstall()))
    _callbacks.append(om.MSceneMessage.addCallback(om.MSceneMessage.kBeforeOpen,lambda *a:uninstall()))
    return refresh()
