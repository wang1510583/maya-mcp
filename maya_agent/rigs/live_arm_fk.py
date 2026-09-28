"""Native live-arm gestures solved into FK rotations, with fixed child offsets.

Only a mouse gesture is isolated. No reference curves, historical matrices or
animated helper transforms are created. The original limb graph still evaluates
playback; all committed keys belong to the existing visible FK controllers.
"""
import json
import math

ROLES=('shoulder_fk','middle_fk','end_fk')
ROT=tuple('rotate'+a for a in 'XYZ')
TR=tuple('translate'+a for a in 'XYZ')+ROT


def selected_role(root):
    import maya.cmds as c
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    if data['kind']!='arm':return None
    selected=c.ls(sl=True,long=True,objectsOnly=True) or []
    for role,proxy in data['controls'].items():
        if selected==c.ls(proxy,long=True):return role
    return None


def begin(root,role):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _snapshot
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    inputs=data['inputs'];controls=data['controls']
    if any(c.objExists(n+'.liveRotationData') for n in inputs.values()):
        raise ValueError('此手臂还包含旧版隐藏旋转参考，请先迁移旧动画。')
    mode=c.contextInfo(c.currentCtx(),c=True)
    if mode=='manipMove' and role=='end_fk' and c.objExists(controls['end_fk']+'.global') and c.getAttr(controls['end_fk']+'.global')>.001:
        raise ValueError('手腕 global=1 正在固定世界位置；请设为 0 后通过 FK 旋转移动手腕。')
    proxy=controls[role];source=inputs[role]
    snapshot=_snapshot([controls[r]+'.'+a for r in ROLES for a in TR])
    world={r:om.MMatrix(c.xform(inputs[r],q=True,ws=True,m=True)) for r in ROLES}
    entry=dict(data=data,role=role,mode=mode,snapshot=snapshot,edges=[],curve_edges=[],world=world,
               proxy=proxy,source=source,changed=False,finished=False)
    entry['solved_world']={r:om.MMatrix(c.xform(data['targets'][r],q=True,ws=True,m=True)) for r in ROLES}
    entry['display']=om.MMatrix(c.xform(proxy,q=True,ws=True,m=True))
    entry['move_goal']=om.MVector(*list(entry['display'])[12:15])
    entry['native_attrs']=TR[:3] if mode=='manipMove' else ROT
    entry['destinations']={inputs[r]+'.'+a:controls[r]+'.'+a for r in ROLES for a in ROT}
    try:
        for attr in TR:
            src=proxy+'.'+attr;dst=source+'.'+attr
            if not c.isConnected(src,dst):
                if attr in entry['native_attrs']:raise ValueError('手臂通道连接已被修改：'+dst)
                continue
            value=c.getAttr(dst);c.disconnectAttr(src,dst);c.setAttr(dst,value)
            entry['edges'].append((src,dst))
            if attr in ROT:entry['destinations'][dst]=dst
        for attr in TR:
            plug=proxy+'.'+attr
            if c.getAttr(plug,lock=True):continue
            incoming=c.connectionInfo(plug,sourceFromDestination=True)
            if incoming:
                value=c.getAttr(plug);c.disconnectAttr(incoming,plug);c.setAttr(plug,value)
                entry['curve_edges'].append((incoming,plug))
        # Native Maya manipulator math assumes its local rotations are the
        # visible handle basis. Historical FK Euler values are a different
        # basis on a solved surface. Use neutral gesture rotations; the live
        # display matrix keeps the handle exactly in its existing world pose.
        local=om.MTransformationMatrix(om.MMatrix(c.getAttr(proxy+'.matrix')))
        local.setRotation(om.MEulerRotation())
        c.setAttr(proxy+'.rotate',0,0,0)
        entry['local']=local.asMatrix()
        entry['parent']=entry['local'].inverse()*entry['display']
        entry['move_parent']=entry['parent']
        entry['native_start']=[c.getAttr(proxy+'.'+a) for a in entry['native_attrs']]
        entry['last_native']=list(entry['native_start'])
        return entry
    except Exception:
        for incoming,plug in entry['curve_edges']:c.connectAttr(incoming,plug,force=True)
        for attr in TR:
            if proxy+'.'+attr in snapshot[0]:c.setAttr(proxy+'.'+attr,snapshot[0][proxy+'.'+attr])
        for src,dst in entry['edges']:c.connectAttr(src,dst,force=True)
        raise


def _position(node):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    return om.MVector(*c.xform(node,q=True,ws=True,t=True))


def _rotate_world(node,world,destinations):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    parent=om.MMatrix(c.getAttr(node+'.offsetParentMatrix'))*om.MMatrix(c.getAttr(node+'.parentMatrix[0]'))
    local=om.MTransformationMatrix(world*parent.inverse()).rotation(asQuaternion=True).asMatrix()
    axis=om.MEulerRotation(*[math.radians(v) for v in c.getAttr(node+'.rotateAxis')[0]]).asMatrix()
    orient=om.MEulerRotation(*[math.radians(v) for v in c.getAttr(node+'.jointOrient')[0]]).asMatrix()
    e=om.MTransformationMatrix(axis.inverse()*local*orient.inverse()).rotation(asQuaternion=True).asEulerRotation()
    order=c.getAttr(node+'.rotateOrder');e.reorderIt(order)
    previous=om.MEulerRotation(*[math.radians(v) for v in c.getAttr(node+'.rotate')[0]],order)
    e=e.closestSolution(previous)
    for attr,value in zip(ROT,e):c.setAttr(destinations[node+'.'+attr],math.degrees(value))


def _aim(node,child,point,destinations):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    a=_position(child)-_position(node);b=point-_position(node)
    if a.length()<1e-8 or b.length()<1e-8:return
    delta=a.rotateTo(b).asMatrix()
    _rotate_world(node,om.MMatrix(c.xform(node,q=True,ws=True,m=True))*delta,destinations)


def update(entry,force=False):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    if entry['finished']:return
    proxy=entry['proxy'];data=entry['data'];inputs=data['inputs'];role=entry['role']
    native=[c.getAttr(proxy+'.'+a) for a in entry['native_attrs']]
    if not force and max(abs(a-b) for a,b in zip(native,entry['last_native']))<1e-10:return
    local=om.MTransformationMatrix(entry['local'])
    if entry['mode']=='manipMove':local.setTranslation(om.MVector(*native),om.MSpace.kTransform)
    else:local.setRotation(om.MEulerRotation(*[math.radians(v) for v in native],c.getAttr(proxy+'.rotateOrder')))
    desired=local.asMatrix()*entry['parent']
    entry['last_native']=native
    entry['changed']=max(abs(a-b) for a,b in zip(native,entry['native_start']))>1e-8
    if entry['mode']=='manipMove' and role!='shoulder_fk':
        delta=om.MVector(*[a-b for a,b in zip(native,entry['native_start'])])*entry['move_parent']
        entry['move_goal']+=delta
        values=list(desired);values[12:15]=list(entry['move_goal']);desired=om.MMatrix(values)
        entry['changed']=(entry['move_goal']-om.MVector(*list(entry['display'])[12:15])).length()>1e-8
    # Every mouse sample solves from its original pose, never the preceding
    # sample. This avoids cumulative drift and makes undo/redo deterministic.
    for r in ROLES:
        for attr in ROT:
            c.setAttr(entry['destinations'][inputs[r]+'.'+attr],entry['snapshot'][0][data['controls'][r]+'.'+attr])
    destinations=entry['destinations']
    if entry['mode']=='manipRotate':
        delta=entry['display'].inverse()*desired
        if role=='middle_fk' and max(abs(a-b) for a,b in zip(entry['world'][role],entry['solved_world'][role]))>1e-6:
            # Re-express an IK/twisted pose as FK rotations at the solved elbow.
            # The child offsets stay constant; no translation/pivot keys or
            # historical reference layer is required. This is done only when
            # editing, never during playback or on an ordinary selection click.
            for r in ROLES:_rotate_world(inputs[r],entry['solved_world'][r],destinations)
            _rotate_world(inputs[role],entry['solved_world'][role]*delta,destinations)
        else:_rotate_world(inputs[role],entry['world'][role]*delta,destinations)
    elif role=='shoulder_fk':
        # The shoulder is the only translation root of the chain.
        for attr,value in zip(TR[:3],native):c.setAttr(inputs[role]+'.'+attr,value)
    else:
        s,e,w=[_position(inputs[r]) for r in ROLES]
        goal=om.MVector(*list(desired)[12:15])
        if role=='middle_fk':
            # The animator grabs the solved elbow, which can differ from the
            # hidden FK input after twists/IK. Aligning the hidden elbow to the
            # visible target creates a finite snap for an infinitesimal drag.
            visible=om.MVector(*list(entry['display'])[12:15])-s
            wanted=goal-s
            if visible.length()>1e-8 and wanted.length()>1e-8:
                _rotate_world(inputs['shoulder_fk'],entry['world']['shoulder_fk']*visible.rotateTo(wanted).asMatrix(),destinations)
        else:
            a=(e-s).length();b=(w-e).length();direction=goal-s
            if direction.length()<1e-8:direction=w-s
            if direction.length()<1e-8:direction=om.MVector(1,0,0)
            distance=max(abs(a-b)+1e-7,min(direction.length(),a+b-1e-7));direction.normalize()
            bend=e-s-direction*((e-s)*direction)
            if bend.length()<1e-8:
                basis=min([om.MVector(1,0,0),om.MVector(0,1,0),om.MVector(0,0,1)],key=lambda v:abs(v*direction))
                bend=basis-direction*(basis*direction)
            bend.normalize()
            x=(a*a-b*b+distance*distance)/(2*distance)
            elbow=s+direction*x+bend*math.sqrt(max(0,a*a-x*x))
            wrist=s+direction*distance
            _aim(inputs['shoulder_fk'],inputs['middle_fk'],elbow,destinations)
            _aim(inputs['middle_fk'],inputs['end_fk'],wrist,destinations)
            _rotate_world(inputs['end_fk'],entry['world']['end_fk'],destinations)
            # Resolve twist in the original solver's bend plane. Merely aiming
            # both links leaves their Z axes in the previous bend plane, so a
            # later Z bend can swing the elbow even though lengths are fixed.
            solved={r:om.MMatrix(c.xform(data['targets'][r],q=True,ws=True,m=True)) for r in ROLES}
            _rotate_world(inputs['shoulder_fk'],solved['shoulder_fk'],destinations)
            _rotate_world(inputs['middle_fk'],solved['middle_fk'],destinations)
            _rotate_world(inputs['end_fk'],entry['world']['end_fk'],destinations)
        # Native mouse input is consumed as a position request. Keep even the
        # visible translation fields fixed after each mouse sample, not merely
        # at release. The next native sample is again relative to mouse-down.
        for attr,value in zip(TR[:3],entry['native_start']):c.setAttr(proxy+'.'+attr,value)
        entry['last_native']=list(entry['native_start'])
        local=om.MTransformationMatrix(entry['local'])
        local.setRotation(om.MEulerRotation(*[math.radians(v) for v in c.getAttr(proxy+'.rotate')[0]],c.getAttr(proxy+'.rotateOrder')))
        entry['move_parent']=local.asMatrix().inverse()*om.MMatrix(c.xform(proxy,q=True,ws=True,m=True))


def finish(entry,cancel=False):
    import maya.cmds as c
    from .live_edit import _restore
    if entry['finished']:return
    if not cancel:update(entry)
    values={src:c.getAttr(dst) for src,dst in entry['edges']}
    for src,dst in entry['edges']:
        # Restore the native display input before reconnecting its solver edge.
        c.setAttr(src,values[src]);c.connectAttr(src,dst,force=True)
    for incoming,plug in entry['curve_edges']:
        value=values.get(plug,entry['snapshot'][0][plug]);c.connectAttr(incoming,plug,force=True);c.setAttr(plug,value)
    for plug,value in values.items():c.setAttr(plug,value)
    entry['finished']=True
    if cancel or not entry['changed']:_restore(entry['snapshot'])
    for r in ('middle_fk','end_fk'):
        proxy=entry['data']['controls'][r]
        for attr in TR[:3]:
            plug=proxy+'.'+attr
            if abs(c.getAttr(plug)-entry['snapshot'][0][plug])>1e-8:
                raise RuntimeError('固定手臂位移校验失败：'+plug)
