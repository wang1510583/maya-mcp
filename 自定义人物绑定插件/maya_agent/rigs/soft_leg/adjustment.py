"""Explicit, persistent setup mode; guides never drive the live solver."""
from contextlib import contextmanager
import json
import math

KEYS=('heel','toe_end','toe')
PIVOTS=('rotatePivot','scalePivot','rotatePivotTranslate','scalePivotTranslate')


@contextmanager
def edit_chunk(name):
    import maya.cmds as c
    undo=c.undoInfo(q=True,state=True)
    auto=c.autoKeyframe(q=True,state=True)
    if undo:c.undoInfo(openChunk=True,chunkName=name)
    try:
        c.autoKeyframe(state=False)
        yield
    finally:
        try:c.autoKeyframe(state=auto)
        finally:
            if undo:c.undoInfo(closeChunk=True)


def resolve(rig):
    import maya.cmds as c
    root=rig['root'] if isinstance(rig,dict) else rig
    if not c.objExists(root):raise ValueError('请先创建或选择一套腿部系统。')
    if not c.objExists(root+'.legSetupData'):
        namespace=root.rsplit('|',1)[-1].rsplit(':',1)[0]
        root=namespace+':rig_root'
    if not c.objExists(root+'.legSetupData'):
        raise ValueError('仅支持本插件创建的腿部系统，原参考系统不会被修改。')
    return root,json.loads(c.getAttr(root+'.legSetupData'))


def pivot_lock(node,locked):
    import maya.cmds as c
    for attr in PIVOTS:
        for axis in 'XYZ':c.setAttr(node+'.'+attr+axis,lock=locked,keyable=False,channelBox=False)


def guide_lock(node,locked):
    import maya.cmds as c
    for axis in 'XYZ':c.setAttr(node+'.translate'+axis,lock=locked,keyable=not locked)


def initialize(rig):
    import maya.cmds as c
    root=rig['root']
    ns=rig['namespace']+':'
    group=c.createNode('transform',name=ns+'setup_guides',parent=root)
    data={'controls':{k:rig['controls'][k] for k in KEYS},'guides':{},'group':group}
    for key in KEYS:
        node=data['controls'][key]
        guide=c.spaceLocator(name=ns+key+'_adjustGuide')[0]
        c.parent(guide,group,relative=True)
        c.xform(guide,ws=True,t=c.xform(node,q=True,ws=True,rp=True))
        shape=c.listRelatives(guide,shapes=True,fullPath=True)[0]
        c.setAttr(shape+'.localScale',.3,.3,.3)
        c.setAttr(shape+'.overrideEnabled',True)
        c.setAttr(shape+'.overrideColor',17)
        for attr in ('rotate','scale'):
            for axis in 'XYZ':c.setAttr(guide+'.'+attr+axis,lock=True,keyable=False)
        c.setAttr(guide+'.visibility',lock=True,keyable=False)
        guide_lock(guide,True)
        pivot_lock(node,True)
        data['guides'][key]=guide
    c.setAttr(group+'.visibility',False,lock=True)
    for attr in ('translate','rotate','scale'):
        for axis in 'XYZ':c.setAttr(group+'.'+attr+axis,lock=True,keyable=False)
    c.addAttr(root,ln='legSetupData',dt='string')
    c.setAttr(root+'.legSetupData',json.dumps(data),type='string',lock=True)
    c.addAttr(root,ln='adjustmentMode',at='bool')
    c.setAttr(root+'.adjustmentMode',False,lock=True,channelBox=True)


def _state(root,data,enabled):
    import maya.cmds as c
    for guide in data['guides'].values():guide_lock(guide,not enabled)
    c.setAttr(data['group']+'.visibility',lock=False)
    c.setAttr(data['group']+'.visibility',enabled,lock=True)
    c.setAttr(root+'.adjustmentMode',lock=False)
    c.setAttr(root+'.adjustmentMode',enabled,lock=True)


def sync_guides(rig):
    import maya.cmds as c
    root,data=resolve(rig)
    for key in KEYS:
        guide=data['guides'][key]
        guide_lock(guide,False)
        c.xform(guide,ws=True,t=display_pivot(root,data,key))
        guide_lock(guide,not c.getAttr(root+'.adjustmentMode'))


def display_pivot(root,data,key,position=None):
    """Map guide points between the solved foot and its hidden input frame."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    node=data['controls'][key]
    live=json.loads(c.getAttr(root+'.liveAlignmentData')) if c.objExists(root+'.liveAlignmentData') else {}
    if key in live.get('toe_follow',{}) and c.getAttr(root+'.liveAlignment'):
        ball=live['toe_follow'][key]
        delta=(om.MMatrix(c.getAttr(ball+'.parentInverseMatrix[0]'))*
               om.MMatrix(c.getAttr(ball+'.matrix'))*om.MMatrix(c.getAttr(ball+'.parentMatrix[0]')))
        if position is None:
            return list(om.MPoint(c.xform(node,q=True,ws=True,rp=True))*delta)[:3]
        return list(om.MPoint(position)*delta.inverse())[:3]
    if key in live.get('pivot_sources',{}) and c.getAttr(root+'.liveAlignment'):
        solved=om.MMatrix(c.xform(live['targets'][key],q=True,ws=True,m=True))
        if position is None:
            return list(om.MPoint(c.getAttr(node+'.rotatePivot')[0])*solved)[:3]
        point=om.MPoint(position)*solved.inverse()*om.MMatrix(c.xform(node,q=True,ws=True,m=True))
        return list(point)[:3]
    return position if position is not None else c.xform(node,q=True,ws=True,rp=True)


def set_pivot(node,position):
    """Change the pivot and locator appearance while retaining the entire transform matrix."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    old_pivot=c.xform(node,q=True,os=True,rp=True)
    pivot_lock(node,False)
    try:
        c.xform(node,ws=True,pivots=position,preserve=True)
        local=om.MPoint(position)*om.MMatrix(c.xform(node,q=True,ws=True,m=True)).inverse()
        for shape in c.listRelatives(node,shapes=True,fullPath=True,type='locator') or []:
            c.setAttr(shape+'.localPosition',local.x,local.y,local.z)
        delta=[local[i]-old_pivot[i] for i in range(3)]
        for shape in c.listRelatives(node,shapes=True,fullPath=True,type='nurbsCurve') or []:
            if c.objExists(shape+'.controllerArtwork') and c.getAttr(shape+'.controllerArtwork'):
                c.move(*delta,shape+'.cv[*]',relative=True,objectSpace=True)
    finally:pivot_lock(node,True)


def set_mode(rig,enabled,cancel=False):
    import maya.cmds as c
    if not isinstance(enabled,bool):raise ValueError('enabled 必须是布尔值')
    root,data=resolve(rig)
    active=c.getAttr(root+'.adjustmentMode')
    if active==enabled:return dict(root=root,enabled=active,guides=data['guides'])
    ns=root.rsplit('|',1)[-1].rsplit(':',1)[0]
    history=c.listHistory(c.ls(ns+':*',type='transform') or []) or []
    animated=bool(c.ls(history,type='animCurve'))
    with edit_chunk('LegAdjustmentMode'):
        if enabled:
            sync_guides(root)
            _state(root,data,True)
        elif cancel:
            sync_guides(root)
            _state(root,data,False)
        else:
            positions={k:c.xform(data['guides'][k],q=True,ws=True,t=True) for k in KEYS}
            if not all(math.isfinite(v) for p in positions.values() for v in p):
                raise ValueError('支点位置必须是有限数字。')
            changed=[k for k in KEYS if math.dist(positions[k],display_pivot(root,data,k))>1e-8]
            positions={k:display_pivot(root,data,k,p) for k,p in positions.items()}
            # Visible handles intentionally move with the edited pivot. Actual
            # solver inputs, output joints and driven targets must stay fixed.
            nodes=[n for n in c.ls(ns+':*',type='transform') if c.objExists(n) and not c.objExists(n+'.liveInput') and not c.objExists(n+'.zeroChannelData')]
            matrices={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
            snapshots={n:{a:c.getAttr(n+'.'+a)[0] for a in PIVOTS} for n in data['controls'].values()}
            shapes={s:c.getAttr(s+'.localPosition')[0] for n in data['controls'].values()
                    for s in c.listRelatives(n,shapes=True,fullPath=True,type='locator') or []}
            artwork={s:c.xform(s+'.cv[*]',q=True,os=True,t=True) for n in data['controls'].values()
                     for s in c.listRelatives(n,shapes=True,fullPath=True,type='nurbsCurve') or []
                     if c.objExists(s+'.controllerArtwork')}
            from .pivot_animation import Edit
            # A previous compensated edit still needs graph-aware handling even
            # if an animator subsequently removes every live animation curve.
            compensated=any(c.listConnections(n+'.rotatePivotTranslate',s=True,d=False) for n in data['controls'].values())
            edit=Edit(root,[data['controls'][k] for k in changed]) if animated or compensated else None
            try:
                for key in changed:
                    if edit:edit.apply(data['controls'][key],positions[key])
                    else:set_pivot(data['controls'][key],positions[key])
                error=max(max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)) for n,m in matrices.items())
                if error>1e-5:raise RuntimeError('调整引起姿态变化，已还原支点：'+str(error))
                _state(root,data,False)
            except Exception:
                if edit:edit.rollback()
                else:
                    for n,attrs in snapshots.items():
                        pivot_lock(n,False)
                        try:
                            for a,value in attrs.items():c.setAttr(n+'.'+a,*value)
                        finally:pivot_lock(n,True)
                for s,value in shapes.items():c.setAttr(s+'.localPosition',*value)
                for s,values in artwork.items():
                    for i in range(len(values)//3):c.xform(s+'.cv[{}]'.format(i),os=True,t=values[i*3:i*3+3])
                raise
    return dict(root=root,enabled=enabled,guides=data['guides'])
