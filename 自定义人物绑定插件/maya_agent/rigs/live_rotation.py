"""Transient rotation handle; all persistent animation belongs to its control.

The gesture reference contains constants only and is removed on mouse release.
An editable pivot on the visible control represents the solved rotation centre
without counter-animating the shoulder, wrist or elbow direction controller.
"""
import json

PIVOTS = tuple('inputPivot'+a for a in 'XYZ')
AXES = tuple('inputAxis'+a for a in 'XYZ')
ORIENTS = tuple('inputOrient'+a for a in 'XYZ')
CHANNELS = PIVOTS+AXES+ORIENTS


def ensure_pivots(root, role):
    import maya.cmds as c
    live=json.loads(c.getAttr(root+'.liveAlignmentData'))
    source=live['inputs'][role];proxy=live['controls'][role]
    changed=False
    for attr in CHANNELS:
        axis=attr[-1];is_pivot=attr in PIVOTS
        dst=source+('.rotatePivot' if is_pivot else '.rotateAxis' if attr in AXES else '.jointOrient')+axis
        if not c.objExists(proxy+'.'+attr):
            if c.connectionInfo(dst,sourceFromDestination=True):
                raise ValueError('External rotation pivot driver: '+dst)
            c.addAttr(proxy,ln=attr,nn=('Input Pivot ' if is_pivot else 'Input Axis ' if attr in AXES else 'Input Orient ')+axis,
                      at='doubleLinear' if is_pivot else 'doubleAngle',keyable=True,
                      dv=c.getAttr(dst))
        if not c.isConnected(proxy+'.'+attr,dst):c.connectAttr(proxy+'.'+attr,dst)
        if not any(e['source']==dst for e in live['entries']):
            live['entries'].append(dict(source=dst,proxy=proxy+'.'+attr,incoming='',value=c.getAttr(dst)))
            changed=True
    if changed:
        c.setAttr(root+'.liveAlignmentData',lock=False)
        c.setAttr(root+'.liveAlignmentData',json.dumps(live),type='string',lock=True)
    return proxy


def _write(node,data):
    import maya.cmds as c
    plug=node+'.liveRotationData'
    if not c.objExists(plug):c.addAttr(node,ln='liveRotationData',dt='string')
    c.setAttr(plug,lock=False);c.setAttr(plug,json.dumps(data),type='string',lock=True)


def install(root,role):
    import maya.cmds as c
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    try:return _install(root,role)
    finally:c.autoKeyframe(state=auto)


def _install(root,role):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _frame
    live=json.loads(c.getAttr(root+'.liveAlignmentData'))
    source=live['inputs'][role];proxy=live['controls'][role]
    old_text=c.getAttr(source+'.liveRotationData') if c.objExists(source+'.liveRotationData') else None
    if old_text:
        raise ValueError('旧版隐藏旋转动画需要先修复，不能继续叠加旋转参考：'+source)
    old={'layers':[]}
    frame=_frame(live['targets'][role]);world=om.MMatrix(c.xform(source,q=True,ws=True,m=True))
    ns=root.rsplit('|',1)[-1].rsplit(':',1)[0]
    entry=dict(source=source,proxy=proxy,old_text=old_text,created=[],edges=[],basis=list(frame*world.inverse()),
               old_op=c.connectionInfo(source+'.offsetParentMatrix',sourceFromDestination=True),
               old_matrix=c.getAttr(source+'.offsetParentMatrix'),
               pivot=list(om.MPoint(*list(frame)[12:15])*world.inverse()))
    import math
    entry['axis']=[math.degrees(v) for v in om.MTransformationMatrix(world*frame.inverse()).rotation()]
    parent=om.MMatrix(c.getAttr(source+'.offsetParentMatrix'))*om.MMatrix(c.getAttr(source+'.parentMatrix[0]'))
    entry['orient']=[math.degrees(v) for v in om.MTransformationMatrix(frame*parent.inverse()).rotation()]
    # Keep an established coordinate system when revisiting an existing key.
    # Only a changed solved pivot/shape offset calls for new calibration.
    if max(abs(c.getAttr(proxy+'.'+a)-v) for a,v in
           list(zip(PIVOTS,entry['pivot']))+list(zip(AXES,entry['axis'])))<1e-6:
        entry['orient']=[c.getAttr(proxy+'.'+a) for a in ORIENTS]
    def create(kind,label,**kwargs):
        n=c.createNode(kind,name=ns+':rotation_'+role+'_'+label,skipSelect=True,**kwargs)
        entry['created'].append(n);return n
    try:
        ref=create('transform','reference',parent=root);entry['reference']=ref
        c.setAttr(ref+'.visibility',False);c.setAttr(ref+'.hiddenInOutliner',True)
        for axis in 'XYZ':
            plug=proxy+'.rotate'+axis;dest=ref+'.rotate'+axis
            value=c.getAttr(plug)
            c.setAttr(dest,value)
            # Freeze only this control's existing rotation consumers. The new
            # layer is the sole consumer of the editable rotation channels.
            for target in c.listConnections(plug,s=False,d=True,p=True) or []:
                if target.split('.')[0] not in [source]+[n for layer in old['layers'] for n in layer['created']]:
                    raise ValueError('External rotation consumer: '+target)
                c.disconnectAttr(plug,target);c.connectAttr(dest,target)
                entry['edges'].append((plug,target,dest))
        order=c.getAttr(proxy+'.rotateOrder');c.setAttr(ref+'.rotateOrder',order)
        live_rot=create('composeMatrix','input');ref_rot=create('composeMatrix','baseline')
        for axis in 'XYZ':c.connectAttr(proxy+'.rotate'+axis,live_rot+'.inputRotate'+axis)
        c.setAttr(live_rot+'.inputRotateOrder',order)
        c.connectAttr(ref+'.rotate',ref_rot+'.inputRotate');c.setAttr(ref_rot+'.inputRotateOrder',order)
        inverse=create('inverseMatrix','baselineInverse');c.connectAttr(ref_rot+'.outputMatrix',inverse+'.inputMatrix')
        result=create('multMatrix','result')
        basis=om.MMatrix(entry['basis'])
        c.connectAttr(source+'.inverseMatrix',result+'.matrixIn[0]')
        c.setAttr(result+'.matrixIn[1]',*list(basis.inverse()),type='matrix')
        c.connectAttr(live_rot+'.outputMatrix',result+'.matrixIn[2]')
        c.connectAttr(inverse+'.outputMatrix',result+'.matrixIn[3]')
        c.setAttr(result+'.matrixIn[4]',*list(basis),type='matrix')
        c.connectAttr(source+'.matrix',result+'.matrixIn[5]')
        if entry['old_op']:c.connectAttr(entry['old_op'],result+'.matrixIn[6]')
        else:c.setAttr(result+'.matrixIn[6]',*entry['old_matrix'],type='matrix')
        c.connectAttr(result+'.matrixSum',source+'.offsetParentMatrix',force=True)
        entry.update(result=result,live_rot=live_rot,ref_rot=ref_rot)
        # Never serialize a gesture or connect a time-driven reference.
        error=max(abs(a-b) for a,b in zip(world,c.xform(source,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('Rotation layer changed the input pose: '+str(error))
        return entry
    except Exception:
        rollback(entry)
        raise


def finish(entry, snapshot, auto_key):
    """Commit the solved gesture to visible TR/pivot channels, then remove it."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _world, TR
    source=entry['source'];proxy=entry['proxy']
    wanted=om.MMatrix(c.xform(source,q=True,ws=True,m=True))
    rollback(entry)
    for attr,value in zip(PIVOTS,entry['pivot']):c.setAttr(proxy+'.'+attr,value)
    for attr,value in zip(AXES,entry['axis']):c.setAttr(proxy+'.'+attr,value)
    for attr,value in zip(ORIENTS,entry['orient']):c.setAttr(proxy+'.'+attr,value)
    m=om.MTransformationMatrix()
    m.setTranslation(om.MVector(*entry['pivot'][:3]),om.MSpace.kTransform)
    _world(source,m.asMatrix()*wanted,{source+'.'+a:proxy+'.'+a for a in TR})
    # Seed newly required channels at existing authored times. This includes a
    # formerly unkeyed translation: changing its constant would alter old poses.
    if auto_key and snapshot[1]:
        times=sorted({t for curve in snapshot[1].values() for t in curve['times']})
        for plug,old in snapshot[0].items():
            value=c.getAttr(plug)
            if abs(value-old)>1e-9 and not c.connectionInfo(plug,sourceFromDestination=True):
                for t in times:c.setKeyframe(plug,time=t,value=old)
                c.setAttr(plug,value)
    error=max(abs(a-b) for a,b in zip(wanted,c.xform(source,q=True,ws=True,m=True)))
    if error>1e-5:raise RuntimeError('Rotation commit changed pose: '+str(error))


def rollback(entry):
    import maya.cmds as c
    node=entry['source'];plug=node+'.offsetParentMatrix'
    incoming=c.connectionInfo(plug,sourceFromDestination=True)
    if incoming:c.disconnectAttr(incoming,plug)
    if entry['old_op']:c.connectAttr(entry['old_op'],plug)
    else:c.setAttr(plug,*entry['old_matrix'],type='matrix')
    for original,target,ref in reversed(entry['edges']):
        if c.isConnected(ref,target):c.disconnectAttr(ref,target)
        c.connectAttr(original,target,force=True)
    for n in reversed(entry['created']):
        if c.objExists(n):c.delete(n)
    if entry['old_text']:_write(node,json.loads(entry['old_text']))
    elif c.objExists(node+'.liveRotationData'):
        c.setAttr(node+'.liveRotationData',lock=False);c.deleteAttr(node+'.liveRotationData')


def solve_rotation(node,desired,proxy):
    """Invert the newest rotation frame for explicit input alignment/moves."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import math
    data=json.loads(c.getAttr(node+'.liveRotationData'));layer=data['layers'][-1]
    basis=om.MMatrix(layer['basis'])
    old_op=om.MMatrix(c.getAttr(layer['old_op'])) if layer['old_op'] else om.MMatrix(layer['old_matrix'])
    baseline=om.MMatrix(c.getAttr(node+'.matrix'))*old_op
    reference=om.MMatrix(c.getAttr(layer['ref_rot']+'.outputMatrix'))
    local=desired*om.MMatrix(c.getAttr(node+'.parentMatrix[0]')).inverse()
    rotation=basis*local*baseline.inverse()*basis.inverse()*reference
    order=c.getAttr(proxy+'.rotateOrder')
    e=om.MTransformationMatrix(rotation).rotation(asQuaternion=True).asEulerRotation();e.reorderIt(order)
    previous=om.MEulerRotation(*[math.radians(v) for v in c.getAttr(proxy+'.rotate')[0]],order)
    e=e.closestSolution(previous)
    for axis,v in zip('XYZ',e):
        plug=proxy+'.rotate'+axis
        if abs(c.getAttr(plug)-math.degrees(v))>1e-9:c.setAttr(plug,math.degrees(v))
    first=data['layers'][0]
    base=om.MMatrix(c.getAttr(first['old_op'])) if first['old_op'] else om.MMatrix(first['old_matrix'])
    return base*om.MMatrix(c.getAttr(node+'.parentMatrix[0]'))
