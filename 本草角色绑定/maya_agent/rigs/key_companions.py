"""Include a gesture's changed calibration channels when native S is used.

No hotkey is replaced. The Maya keying procedure still keys the selection;
only unkeyed companion changes from this runtime's completed gesture join it.
"""
_pending={}
_callbacks=[]
_session=None
_native_key=False


def remember(gesture):
    if gesture['auto']:return
    import maya.cmds as c
    from . import scene_data
    frame=c.currentTime(q=True)
    for entry in gesture.get('arm_gestures',[]):
        root=entry['data']['root']
        if not (entry.get('foot_move') or entry.get('foot_rotation')) and not c.objExists(root+'.armWorldIKData') and not (
                c.objExists(root+'.liveAlignmentData') and scene_data.read(root+'.liveAlignmentData')['kind']=='arm'):continue
        old=_pending.get(root)
        if not old or old['frame']!=frame:
            old=dict(frame=frame,values={});_pending[root]=old
        for p,v in entry['snapshot'][0].items():old['values'].setdefault(p,v)


def _begin(identity):
    import maya.cmds as c
    from . import scene_data,live_edit
    global _session
    if _session or globals().get('_runtime_disabled',False):return
    # Do not turn a canceled prompt or explicit Channel Box subset into keys.
    if any(c.optionVar(exists=n) and c.optionVar(q=n) for n in ('setKeyframePrompt','keyUseChannelBox')):return
    roots=set(live_edit._roots())
    roots={n.rsplit('|',1)[-1] for n in roots}
    for node in c.ls(sl=True,long=True) or []:
        if c.objExists(node+'.zeroChannelData'):
            roots.add(scene_data.read(node+'.zeroChannelData')['root'].rsplit('|',1)[-1])
    before={}
    for root,data in _pending.items():
        if root.rsplit('|',1)[-1] in roots and data['frame']==c.currentTime(q=True):
            before.update({p:v for p,v in data['values'].items() if c.objExists(p) and not c.getAttr(p,lock=True)})
    final={p:c.getAttr(p) for p in before}
    if not any(abs(final[p]-v)>1e-8 for p,v in before.items()):return
    snapshot=live_edit._snapshot(before)
    c.undoInfo(openChunk=True,chunkName='KeyRigPose')
    _session=dict(identity=identity,before=before,final=final,snapshot=snapshot)
    try:live_edit._fence('before',[snapshot])
    except Exception:
        _session=None;c.undoInfo(closeChunk=True);raise


def _finish():
    import maya.cmds as c
    from . import live_layers,live_edit
    global _session
    state=_session;_session=None
    if not state:return
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    try:
        final=state['final'];before=state['before']
        for p,v in final.items():c.setAttr(p,v)
        layer=live_layers.edit_layer()
        if layer:live_layers.commit(layer,[(before,{})],True)
        else:
            for p,v in final.items():
                if abs(v-before[p])>1e-8:c.setKeyframe(p,time=c.currentTime(q=True),value=v)
        for p,v in final.items():c.setAttr(p,v)
        live_edit._fence('after',[live_edit._snapshot(final)])
    finally:c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)


def uninstall():
    import maya.api.OpenMaya as om
    for callback in _callbacks:
        try:om.MMessage.removeCallback(callback)
        except RuntimeError:pass
    _callbacks[:]=[];_pending.clear()


def install():
    if globals().get('_runtime_disabled',False) or _callbacks:return
    import maya.api.OpenMaya as om
    _callbacks.append(om.MEventMessage.addEventCallback('timeChanged',lambda *_:_pending.clear()))
    for event in (om.MSceneMessage.kBeforeNew,om.MSceneMessage.kBeforeOpen):
        _callbacks.append(om.MSceneMessage.addCallback(event,lambda *_:_pending.clear()))


def procedure(name,identity,entering,kind,*_):
    # Maya permits one procedure callback; zero_manual owns the shared hook.
    global _native_key
    if globals().get('_runtime_disabled',False):return
    if name=='performSetKeyframeArgList':
        _native_key=entering;return
    if name!='doSetKeyframeArgList':return
    if entering and _native_key:_begin(identity)
    elif _session and _session['identity']==identity:_finish()
