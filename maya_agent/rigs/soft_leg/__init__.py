"""Packaged replica of the inspected soft IK leg and reverse-foot system."""
import json
import math
from pathlib import Path
import re

VERSION = '1.1.0'
DATA = Path(__file__).parent / 'data'


def cleanup(namespace):
    """Remove owned constraints first to protect externally driven objects."""
    import maya.cmds as c
    for node in c.ls(namespace+':*', type='constraint', long=True) or []:
        if c.objExists(node): c.delete(node)
    for node in sorted(c.ls(namespace+':*', long=True) or [], key=lambda n:n.count('|'), reverse=True):
        if c.objExists(node): c.delete(node)
    if c.namespace(exists=namespace): c.namespace(removeNamespace=namespace)


def _build_template(namespace='customLeg', offset=(0.0, 0.0, 0.0)):
    import maya.cmds as c
    from maya_agent.rigs.soft_limb.native import create
    from .adjustment import initialize
    if not isinstance(namespace,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',namespace):
        raise ValueError('命名空间只能使用英文字母、数字和下划线，不能以数字开头。')
    if len(offset)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in offset):
        raise ValueError('offset 必须包含三个有限数字。')
    if c.currentUnit(q=True,linear=True)!='cm' or c.currentUnit(q=True,angle=True)!='deg' or c.upAxis(q=True,axis=True)!='y':
        raise ValueError('此腿部模板要求厘米、度和 Y 轴向上。')
    spec=json.loads((DATA/'leg_v1.json').read_text(encoding='utf-8'))
    base, index=namespace,2
    while c.namespace(exists=':'+namespace):
        namespace='{}_{:02d}'.format(base,index)
        index+=1
    selection=c.ls(sl=True,long=True) or []
    old_namespace=c.namespaceInfo(currentNamespace=True)
    undo=c.undoInfo(q=True,state=True)
    auto=c.autoKeyframe(q=True,state=True)
    if undo:c.undoInfo(openChunk=True,chunkName='CreateCustomLegRig')
    try:
        c.autoKeyframe(state=False)
        c.namespace(setNamespace=':')
        c.namespace(add=namespace)
        create(DATA/'leg_v1.ma',spec,namespace)
        error=0.0
        for name,expected in spec['world_matrices'].items():
            matrix=c.xform(namespace+':'+name,q=True,ws=True,m=True)
            error=max(error,max(abs(a-b) for a,b in zip(matrix,expected)))
        if error>1e-4:raise RuntimeError('腿部复刻姿态校验失败：'+str(error))
        root=c.createNode('transform',name=namespace+':rig_root',skipSelect=True)
        for name in spec['roots']:c.parent(namespace+':'+name,root,relative=True)
        c.setAttr(root+'.translate',*offset)
        for name,expected in spec['world_matrices'].items():
            wanted=list(expected)
            wanted[12:15]=[a+b for a,b in zip(wanted[12:15],offset)]
            matrix=c.xform(namespace+':'+name,q=True,ws=True,m=True)
            if max(abs(a-b) for a,b in zip(matrix,wanted))>1e-4:
                raise RuntimeError('腿部整体偏移校验失败：'+name)
        c.addAttr(root,ln='customLegVersion',dt='string')
        c.setAttr(root+'.customLegVersion',VERSION,type='string',lock=True)
        rig=dict(namespace=namespace,root=root,version=VERSION,baseline_max_error=error,
                 controls={k:namespace+':'+v for k,v in spec['controls'].items()},
                 joints=[namespace+':joint'+str(i) for i in range(1,5)])
        initialize(rig)
        rig['nodes']=c.ls(namespace+':*',long=True)
        return rig
    except Exception:
        cleanup(namespace)
        raise
    finally:
        try:
            c.namespace(setNamespace=old_namespace)
            c.autoKeyframe(state=auto)
            c.select([n for n in selection if c.objExists(n)],r=True) if selection else c.select(clear=True)
        finally:
            if undo:c.undoInfo(closeChunk=True)


def build_from_selection(targets=None, namespace='customLeg', drive_targets=True, copy_animation=False,
                         start_frame=None,end_frame=None,sample_step=1.0,side='L'):
    from .selection import build_from_selection as create
    return create(targets,namespace,drive_targets,copy_animation,start_frame,end_frame,sample_step,side)


build=build_from_selection


def set_adjustment_mode(rig, enabled, cancel=False):
    from .adjustment import set_mode
    return set_mode(rig,enabled,cancel=cancel)


def show_ui():
    from .ui import show
    return show()
