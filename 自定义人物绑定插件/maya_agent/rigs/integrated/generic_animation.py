"""Retain sampled world poses when an animated prop gains a new parent space."""
import json
import math

TR=('translateX','translateY','translateZ','rotateX','rotateY','rotateZ')


def has_animation(target):
    import maya.cmds as c
    node=target
    while node:
        if c.keyframe(node,at=list(TR)+['scaleX','scaleY','scaleZ'],q=True,tc=True):return True
        node=(c.listRelatives(node,p=True,f=True) or [None])[0]
    return False


def sample_times(target):
    import maya.cmds as c
    current=c.currentTime(q=True)
    start=c.playbackOptions(q=True,min=True);end=c.playbackOptions(q=True,max=True)
    times={current,start,end};node=target
    while node:
        times.update(c.keyframe(node,q=True,tc=True) or [])
        node=(c.listRelatives(node,p=True,f=True) or [None])[0]
    start=min(times);end=max(times)
    if end-start>10000:raise ValueError('通用动画范围超过 10000 帧，请缩小动画范围后创建。')
    times.update(start+i for i in range(int(math.floor(end-start))+1))
    return sorted(times)


def capture(target,original_data=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    frame=c.currentTime(q=True);poses={}
    parent=None
    if original_data and original_data.get('original_parent_uuid'):
        found=c.ls(original_data['original_parent_uuid'],l=True) or []
        if len(found)!=1:raise ValueError('通用物件的原父级已丢失，不能恢复原动画。')
        parent=found[0]
    try:
        for f in sample_times(target):
            c.currentTime(f)
            if original_data:
                prefix=original_data['owner'].rsplit('_mode',1)[0]
                matrix=om.MMatrix(c.getAttr(target+'.matrix'))*om.MMatrix(c.getAttr(prefix+'_originalParentOffset.outMatrix'))
                if parent:matrix*=om.MMatrix(c.xform(parent,q=True,ws=True,m=True))
                poses[f]=list(matrix)
            else:poses[f]=c.xform(target,q=True,ws=True,m=True)
    finally:c.currentTime(frame)
    return poses


def restore(control,receipt):
    import maya.cmds as c
    for attr,edge in receipt['inputs'].items():
        plug=control+'.'+attr;current=c.connectionInfo(plug,sfd=True)
        if current:c.disconnectAttr(current,plug)
        if edge:c.connectAttr(edge,plug)
        else:c.setAttr(plug,receipt['values'][attr])
    backup=receipt.get('backup')
    if backup and c.objExists(backup):
        pairs=c.listConnections(backup+'.sourceCurves',s=True,d=False,p=True,c=True) or []
        for dst,src in zip(pairs[::2],pairs[1::2]):c.disconnectAttr(src,dst)
    for node in reversed(receipt['nodes']):
        if c.objExists(node):c.delete(node)


def bake(data,control,poses):
    """Solve first, then replace TR curves transactionally; originals stay backed up."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .builder import pose_preserving_euler
    frame=c.currentTime(q=True);helper=None;receipt=None
    selection=c.ls(sl=True,long=True) or []
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        before_error=0.
        for f,wanted in poses.items():
            c.currentTime(f);before_error=max(before_error,error(wanted,c.xform(control,q=True,ws=True,m=True)))
        if before_error<=1e-5:return None
        c.currentTime(frame)
        inputs={a:c.connectionInfo(control+'.'+a,sfd=True) for a in TR}
        values={a:c.getAttr(control+'.'+a) for a in TR}
        for a,edge in inputs.items():
            if c.getAttr(control+'.'+a,lock=True):raise ValueError('保留通用动画需要可编辑的位移旋转通道：'+a)
            if edge and not c.nodeType(edge.split('.')[0]).startswith('animCurveT'):
                raise ValueError('通用动画存在外部驱动或动画层，未覆盖：'+control+'.'+a)
        prefix=data['owner'].rsplit('_mode',1)[0]
        parent=c.listRelatives(control,p=True,f=True)[0]
        helper=c.createNode(c.nodeType(control),name=prefix+'_animationSolve',parent=parent,skipSelect=True)
        attrs=['scale','shear','rotateAxis','rotatePivot','rotatePivotTranslate','scalePivot','scalePivotTranslate']
        if c.nodeType(control)=='joint':attrs+=['jointOrient','inverseScale']
        solved={};previous=None
        for f,wanted in poses.items():
            c.currentTime(f)
            shared={a:c.getAttr(control+'.'+a)[0] for a in attrs}
            for a,v in shared.items():c.setAttr(helper+'.'+a,*v)
            order=c.getAttr(control+'.rotateOrder');c.setAttr(helper+'.rotateOrder',order)
            if c.nodeType(control)=='joint':c.setAttr(helper+'.segmentScaleCompensate',c.getAttr(control+'.segmentScaleCompensate'))
            c.setAttr(helper+'.offsetParentMatrix',*c.getAttr(control+'.offsetParentMatrix'),type='matrix')
            c.xform(helper,ws=True,m=wanted)
            for a,v in shared.items():c.setAttr(helper+'.'+a,*v)
            rotation=om.MEulerRotation(*[math.radians(v) for v in c.getAttr(helper+'.rotate')[0]],order)
            rotation=pose_preserving_euler(rotation,previous);previous=rotation
            c.setAttr(helper+'.rotate',*[math.degrees(v) for v in rotation])
            actual=c.xform(helper,q=True,ws=True,m=True)
            delta=om.MVector(*[a-b for a,b in zip(wanted[12:15],actual[12:15])])
            effective=om.MMatrix(c.getAttr(helper+'.offsetParentMatrix'))*om.MMatrix(c.xform(parent,q=True,ws=True,m=True))
            delta*=effective.inverse()
            c.setAttr(helper+'.translate',*[a+b for a,b in zip(c.getAttr(helper+'.translate')[0],delta)])
            if error(wanted,c.xform(helper,q=True,ws=True,m=True))>1e-5:
                raise ValueError('通用动画不能只用位移旋转保留原姿态，帧 '+str(f))
            solved[f]=[c.getAttr(helper+'.'+a) for a in TR]
        c.currentTime(frame)
        receipt=dict(version=1,inputs=inputs,values=values,nodes=[])
        backup=c.createNode('network',name=prefix+'_sourceAnimationBackup',skipSelect=True);receipt['backup']=backup;receipt['nodes'].append(backup)
        c.addAttr(backup,ln='originalConnections',dt='string');c.setAttr(backup+'.originalConnections',json.dumps(inputs),type='string')
        c.addAttr(backup,ln='sourceCurves',at='message',multi=True)
        for i,n in enumerate(sorted({e.split('.')[0] for e in inputs.values() if e})):
            c.connectAttr(n+'.message',backup+'.sourceCurves[%d]'%i)
        for a,edge in inputs.items():
            if edge:c.disconnectAttr(edge,control+'.'+a)
        for a in TR:
            curve=c.createNode('animCurveTA' if a.startswith('rotate') else 'animCurveTL',name=prefix+'_baked_'+a,skipSelect=True)
            receipt['nodes'].append(curve);c.connectAttr(curve+'.output',control+'.'+a)
            for f,v in solved.items():c.setKeyframe(curve,t=f,v=v[TR.index(a)],itt='linear',ott='linear')
        worst=0.
        target=c.ls(data['target_uuid'],l=True)[0]
        for f,wanted in poses.items():
            c.currentTime(f)
            for n in (target,control):worst=max(worst,error(wanted,c.xform(n,q=True,ws=True,m=True)))
        if worst>1e-5:raise RuntimeError('通用动画转换核对失败，已回退：'+str(worst))
        receipt.update(start=min(poses),end=max(poses),sample_count=len(poses),max_world_error=worst,previous_world_error=before_error)
        return receipt
    except Exception:
        if receipt:restore(control,receipt)
        raise
    finally:
        if helper and c.objExists(helper):c.delete(helper)
        c.currentTime(frame)
        selected=[n for n in selection if c.objExists(n)]
        c.select(selected,r=True) if selected else c.select(clear=True)


def repair(character,owner):
    """Explicitly rebase an existing unswitched prop's transferred source curves."""
    import maya.cmds as c
    from .generic_objects import _data
    data=_data(owner)
    if data.get('animation_transfer'):raise ValueError('此通用物件已经转换过动画，不重复转换。')
    if c.getAttr(data['global_plug'])!=0 or c.keyframe(data['global_plug'],q=True,tc=True):
        raise ValueError('通用物件已有空间切换动画，不能自动推断原姿态。')
    for n in data['offsets']:
        if c.keyframe(n,q=True,tc=True) or any(abs(v)>1e-10 for a in ('translate','rotate') for v in c.getAttr(n+'.'+a)[0]):
            raise ValueError('通用物件已有空间匹配编辑，未覆盖。')
    target=c.ls(data['target_uuid'],l=True)[0];control=c.ls(data['control_uuid'],l=True)[0]
    old_owner=c.getAttr(owner+'.genericSpaceData');old_rig=c.getAttr(character+'.integratedRigData')
    auto=c.autoKeyframe(q=True,state=True);receipt=None
    c.undoInfo(openChunk=True,chunkName='PreserveGenericAnimation');c.autoKeyframe(state=False)
    try:
        poses=capture(target,data);receipt=bake(data,control,poses)
        if not receipt:return dict(changed=False)
        data['animation_transfer']=receipt;data['created']+=receipt['nodes']
        rig=json.loads(old_rig);rig['generic_objects']=[data if r['target_uuid']==data['target_uuid'] else r for r in rig['generic_objects']]
        for n,a,v in ((owner,'genericSpaceData',json.dumps(data)),(character,'integratedRigData',json.dumps(rig,ensure_ascii=False))):
            c.setAttr(n+'.'+a,lock=False);c.setAttr(n+'.'+a,v,type='string',lock=True)
        return dict(changed=True,**{k:receipt[k] for k in ('start','end','sample_count','max_world_error','previous_world_error','backup')})
    except Exception:
        if receipt:restore(control,receipt)
        for n,a,v in ((owner,'genericSpaceData',old_owner),(character,'integratedRigData',old_rig)):
            c.setAttr(n+'.'+a,lock=False);c.setAttr(n+'.'+a,v,type='string',lock=True)
        raise
    finally:c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)
