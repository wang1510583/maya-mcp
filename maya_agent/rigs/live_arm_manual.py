"""Live arm gestures using the original, freely editable manual-alignment rig.

The visible handle is an input surface, not an alternative two-bone IK solver.
Align once per gesture, then solve the requested world transform into the same
original input that an animator would manipulate after manual alignment.
"""
import math
import json


if '_alignment_fallbacks' not in globals():_alignment_fallbacks=[]
if '_fallback_notified' not in globals():_fallback_notified=set()
if '_refresh_holds' not in globals():_refresh_holds=set()


def _record_fallback(error,phase):
    """Keep bounded diagnostics without serializing transient state in a rig."""
    import maya.cmds as c
    _alignment_fallbacks.append(dict(root=error.root,error=error.error,phase=phase,frame=c.currentTime(q=True)))
    del _alignment_fallbacks[:-16]
    identity=(c.ls(error.root,uuid=True) or [error.root])[0]
    if identity not in _fallback_notified:
        _fallback_notified.add(identity)
        c.warning('此姿态暂不适合自动校准，已保留当前姿态并继续使用原输入通道：'+error.root.rsplit('|',1)[-1])


def selected_roles(root):
    import maya.cmds as c
    if not c.objExists(root+'.liveAlignmentData'):
        from . import arm_ik,arm_ik_shared
        d=arm_ik._data(root)
        return ['end_fk'] if arm_ik_shared.active(root) and set(c.ls(sl=True,long=True) or []).intersection(c.ls(d['fk_wrist'],long=True)) else []
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    if data['kind']!='arm':return []
    selected=set(c.ls(sl=True,long=True,objectsOnly=True) or [])
    return [r for r in ('shoulder_fk','middle_fk','end_fk')
            if selected.intersection(c.ls(data['controls'][r],long=True) or [])]


def selected_role(root):
    roles=selected_roles(root)
    return roles[0] if len(roles)==1 else None


def begin_many(root,roles):
    """Share one alignment/snapshot per arm, in source parent-to-child order."""
    roles=[role for role in ('shoulder_fk','middle_fk','end_fk') if role in roles]
    if not roles:raise ValueError('No live arm controls selected')
    if len(roles)==1:return begin(root,roles[0])
    children=[]
    try:
        for role in roles:
            setup=children[0]['setup'] if children else None
            children.append(begin(root,role,_setup=setup))
        return dict(children=children,snapshot=children[0]['snapshot'],data=children[0]['data'],
                    mode=children[0]['mode'],role='multiple',finished=False,changed=False)
    except Exception:
        for child in reversed(children):finish(child,cancel=True)
        raise


def begin(root,role,_setup=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import prepare, _restore, _frame, PosePreservationError, TR
    from . import arm_ik_shared
    if arm_ik_shared.active(root,role):return arm_ik_shared.begin(root,_setup)
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    if any(c.objExists(n+'.liveRotationData') for n in data['inputs'].values()):
        raise ValueError('此手臂还包含旧版隐藏旋转参考，请先迁移旧动画。')
    mode=c.contextInfo(c.currentCtx(),c=True)
    if _setup is not None:snapshot,aligned=_setup
    else:
        aligned=True
        try:snapshot=prepare(root,wrist_only=(role=='end_fk' and mode=='manipRotate'))
        except PosePreservationError as exc:
            # prepare has already restored the exact pre-alignment channels and
            # curves. Retain this pose and interpret the gesture as a world delta.
            snapshot=exc.snapshot;aligned=False;_record_fallback(exc,'begin')
    proxy=data['controls'][role];source=data['inputs'][role]
    entry=dict(data=data,role=role,mode=mode,snapshot=snapshot,proxy=proxy,source=source,
               edges=[],curve_edges=[],changed=False,finished=False)
    entry['setup']=(snapshot,aligned)
    entry['destinations']={e['source']:e['proxy'] for e in data['entries']}
    try:
        display=om.MMatrix(c.xform(proxy,q=True,ws=True,m=True))
        entry['input_basis']=om.MMatrix() if aligned else _frame(source)*display.inverse()
        # A multi-object rotation about a shared pivot also changes translation.
        entry['native_attrs']=TR
        for attr in TR:
            src=proxy+'.'+attr;dst=source+'.'+attr
            if not c.isConnected(src,dst):
                if not c.getAttr(src,lock=True):raise ValueError('手臂通道连接已被修改：'+dst)
                continue
            value=c.getAttr(dst);c.disconnectAttr(src,dst);c.setAttr(dst,value)
            entry['edges'].append((src,dst));entry['destinations'][dst]=dst
        for attr in TR:
            plug=proxy+'.'+attr
            if c.getAttr(plug,lock=True):continue
            incoming=c.connectionInfo(plug,sourceFromDestination=True)
            if incoming:
                value=c.getAttr(plug);c.disconnectAttr(incoming,plug);c.setAttr(plug,value)
                entry['curve_edges'].append((incoming,plug))
        # Neutral local rotations make Maya's manipulator use the displayed
        # axes rather than the historical Euler values of the hidden input.
        local=om.MTransformationMatrix(om.MMatrix(c.getAttr(proxy+'.matrix')))
        local.setRotation(om.MEulerRotation());c.setAttr(proxy+'.rotate',0,0,0)
        entry['local']=local.asMatrix();entry['parent']=entry['local'].inverse()*display
        entry['display_edge']=c.connectionInfo(proxy+'.offsetParentMatrix',sourceFromDestination=True)
        dag_parent=c.listRelatives(proxy,parent=True,fullPath=True)
        parent_inverse=om.MMatrix(c.getAttr(dag_parent[0]+'.worldInverseMatrix[0]')) if dag_parent else om.MMatrix()
        entry['native_opm']=entry['parent']*parent_inverse
        entry['native_start']=[c.getAttr(proxy+'.'+a) for a in entry['native_attrs']]
        entry['last_native']=list(entry['native_start'])
        prepare_native_sample(entry,suspend=False)
        return entry
    except Exception:
        if entry.get('display_edge'):restore_display(entry)
        for incoming,plug in entry['curve_edges']:c.connectAttr(incoming,plug,force=True)
        for src,dst in entry['edges']:c.connectAttr(src,dst,force=True)
        _restore(snapshot)
        raise


def prepare_native_sample(entry,suspend=True):
    """Give Maya a stable input parent while it converts mouse motion to TR.

    The solved display can drift away from the freely moved input elbow. Using
    that changing display parent inside Maya's next mouse sample feeds solver
    motion back into the gesture. Restore the output display before repaint.
    """
    import maya.cmds as c
    if 'children' in entry:
        try:
            for child in entry['children']:prepare_native_sample(child,suspend=suspend)
        except Exception:
            restore_display(entry)
            raise
        return
    if suspend and not entry.get('resume_refresh'):
        if not _refresh_holds:c.refresh(suspend=True)
        _refresh_holds.add(id(entry));entry['resume_refresh']=True
    plug=entry['proxy']+'.offsetParentMatrix';edge=entry['display_edge']
    try:
        if edge and c.isConnected(edge,plug):c.disconnectAttr(edge,plug)
        c.setAttr(plug,*list(entry['native_opm']),type='matrix')
    except Exception:
        restore_display(entry)
        raise


def restore_display(entry):
    import maya.cmds as c
    if 'children' in entry:
        for child in entry['children']:restore_display(child)
        return
    edge=entry['display_edge'];plug=entry['proxy']+'.offsetParentMatrix'
    try:
        if edge and not c.isConnected(edge,plug):c.connectAttr(edge,plug,force=True)
    finally:
        if entry.pop('resume_refresh',False):
            _refresh_holds.discard(id(entry))
            if not _refresh_holds:c.refresh(suspend=False);c.refresh(force=True)


def update(entry,force=False,_restore_display=True):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _world
    if entry['finished']:return
    if 'children' in entry:
        try:
            for child in entry['children']:update(child,force=True,_restore_display=False)
            entry['changed']=any(child['changed'] for child in entry['children'])
        finally:restore_display(entry)
        return
    proxy=entry['proxy']
    native=[c.getAttr(proxy+'.'+a) for a in entry['native_attrs']]
    if not force and max(abs(a-b) for a,b in zip(native,entry['last_native']))<1e-10:
        if _restore_display:restore_display(entry)
        return
    entry['last_native']=native
    entry['changed']=max(abs(a-b) for a,b in zip(native,entry['native_start']))>1e-8
    local=om.MTransformationMatrix(entry['local'])
    local.setTranslation(om.MVector(*native[:3]),om.MSpace.kTransform)
    local.setRotation(om.MEulerRotation(*[math.radians(v) for v in native[3:]],c.getAttr(proxy+'.rotateOrder')))
    desired=entry['input_basis']*local.asMatrix()*entry['parent']
    try:_world(entry['source'],desired,entry['destinations'])
    finally:
        if _restore_display:restore_display(entry)


def _reconnect(entry,values):
    import maya.cmds as c
    if entry.get('shared_ik'):
        from .arm_ik_shared import reconnect
        reconnect(entry);return
    for src,dst in entry['edges']:
        c.setAttr(src,values[src]);c.connectAttr(src,dst,force=True)
    for incoming,plug in entry['curve_edges']:
        c.connectAttr(incoming,plug,force=True)
    for plug,dst in entry['edges']:c.setAttr(plug,values[plug])
    entry['finished']=True


def finish(entry,cancel=False):
    import maya.cmds as c
    from .live_edit import _restore,prepare,PosePreservationError
    if entry['finished']:return
    try:
        if not cancel:update(entry)
    except Exception:
        finish(entry,cancel=True)
        raise
    restore_display(entry)
    children=entry.get('children',[entry])
    # Capture every solution before reconnecting any animated parent or child.
    values={src:c.getAttr(dst) for child in children for src,dst in child['edges']}
    for child in children:_reconnect(child,values)
    for plug,value in values.items():c.setAttr(plug,value)
    entry['finished']=True
    if cancel or not entry['changed']:_restore(entry['snapshot'])
    elif any(child.get('shared_ik') for child in children):return
    else:
        # Store the same canonical pose that the next gesture will start from.
        # Otherwise a moved elbow is keyed as an offset at frame A, then the
        # next bend at frame B keys its conversion into shoulder rotation.
        # Those two encodings interpolate differently despite a held shoulder.
        try:prepare(entry['data']['root'],wrist_only=(entry['role']=='end_fk' and entry['mode']=='manipRotate'))
        except PosePreservationError as exc:
            # Reject only the optional re-encoding. Its rollback snapshot is
            # the completed drag, not mouse-down. after_drag can still commit
            # that valid pose to the existing controls and undo it normally.
            entry['alignment_fallback']=True
            _record_fallback(exc,'finish')
        except Exception:
            _restore(entry['snapshot'])
            raise
