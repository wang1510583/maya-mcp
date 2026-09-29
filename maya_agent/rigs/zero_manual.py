"""Adapt Easy Rig's MEL recalculation to the zero-based animator channels.

Only the named recalculation procedure and this plugin's marked rigs are
handled. The vendor's original targets and alignment algorithm remain intact.
"""
import json

if '_callback' not in globals():_callback=None
if '_session' not in globals():_session=None


def install():
    import maya.api.OpenMaya as om
    global _callback
    if _callback is not None:return
    def procedure(name,identity,entering,kind,*_):
        if name!='kurok_recalculate_system':return
        if entering:_begin(identity)
        elif _session and _session['identity']==identity:_finish()
    _callback=om.MCommandMessage.addProcCallback(procedure)


def _begin(identity):
    import maya.cmds as c
    from . import zero_channels,live_edit
    global _session
    if _session:return
    roots=[]
    for n in c.ls(sl=True,long=True,objectsOnly=True) or []:
        if c.objExists(n+'.zeroChannelData'):
            roots.append(json.loads(c.getAttr(n+'.zeroChannelData'))['root'])
    if not roots:return
    entries=[]
    for root in dict.fromkeys(roots):
        if not c.objExists(root+'.zeroPartData'):continue
        d=json.loads(c.getAttr(root+'.zeroPartData'))
        registry=root.rsplit(':',1)[0]+':recalculate_node'
        if not c.objExists(registry):continue
        animated=set()
        for a in c.listAttr(registry,userDefined=True) or []:
            if a.startswith(('zero','animated_object','to_pivot_translate_orient')) and a!='zeroSurfaceLinks':
                animated.update(c.listConnections(registry+'.'+a,s=True,d=False) or [])
        for role,source in d['sources'].items():
            if source not in animated or role not in d['controls']:continue
            control=d['controls'][role];offsets=json.loads(c.getAttr(control+'.zeroChannelData'))['offsets']
            for attr in offsets:
                plug=source+'.'+attr;edge=c.connectionInfo(plug,sfd=True)
                if edge and not c.getAttr(plug,lock=True):entries.append((plug,edge,control+'.'+attr,c.getAttr(plug)))
    if not entries:return
    c.undoInfo(openChunk=True,chunkName='RecalculateZeroControllers')
    _session=dict(identity=identity,entries=entries,auto=c.autoKeyframe(q=True,state=True),
                  curves=set(c.ls(type='animCurve')),snapshot=live_edit._snapshot([e[2] for e in entries]))
    c.autoKeyframe(state=False)
    try:
        for plug,edge,_,value in entries:c.disconnectAttr(edge,plug);c.setAttr(plug,value)
    except Exception:
        _finish(cancel=True)
        # Prevent the vendor from editing a partly detached rig.
        c.select(cl=True);raise


def _finish(cancel=False):
    import maya.cmds as c
    from . import zero_channels,live_edit
    global _session
    state=_session;_session=None
    if not state:return
    owned=set();values={};keys={}
    try:
        for plug,edge,control,_ in state['entries']:
            values[control]=c.getAttr(plug)-zero_channels.offset(control)
            incoming=c.connectionInfo(plug,sfd=True)
            if incoming and incoming!=edge:
                curve=incoming.split('.')[0]
                if not c.nodeType(curve).startswith('animCurve') or curve in state['curves']:
                    raise ValueError('手动对齐产生了未识别的输入，已恢复零位控制器：'+plug)
                owned.add(curve)
                keys[control]=list(zip(c.keyframe(curve,q=True,tc=True) or [],
                                      c.keyframe(curve,q=True,vc=True) or [],
                                      c.keyTangent(curve,q=True,itt=True) or [],
                                      c.keyTangent(curve,q=True,ott=True) or []))
        for plug,edge,_,_ in state['entries']:c.connectAttr(edge,plug,force=True)
        if owned:c.delete(list(owned));owned.clear()
        if cancel:live_edit._restore(state['snapshot']);return
        for control,samples in keys.items():
            offset=zero_channels.offset(control)
            for time,value,itt,ott in samples:
                c.setKeyframe(control,time=time,value=value-offset,itt=itt,ott=ott)
        for control,value in values.items():c.setAttr(control,value)
    except Exception:
        for plug,edge,_,_ in state['entries']:
            if not c.isConnected(edge,plug):c.connectAttr(edge,plug,force=True)
        if owned:c.delete(list(owned))
        from .live_layers import curves_for_plug
        new=set()
        for control in state['snapshot'][0]:new.update(curves_for_plug(control)-state['curves'])
        if new:c.delete(list(new))
        live_edit._restore(state['snapshot']);raise
    finally:c.autoKeyframe(state=state['auto']);c.undoInfo(closeChunk=True)
