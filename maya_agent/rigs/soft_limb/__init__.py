"""Reconstruct the inspected FK / soft stretch limb from its packaged native graph."""
import json
import math
from pathlib import Path
import re

VERSION = '1.3.1'
DATA = Path(__file__).parent / 'data'


def build_from_selection(targets=None, namespace='customArm', drive_targets=True, copy_animation=False,
                         start_frame=None, end_frame=None, sample_step=1.0, side='L'):
    from .selection import build_from_selection as create
    return create(targets=targets, namespace=namespace, drive_targets=drive_targets,copy_animation=copy_animation,
                  start_frame=start_frame,end_frame=end_frame,sample_step=sample_step,side=side)


def show_ui():
    from .ui import show
    return show()


def build(namespace='limbReplica', offset=(0.0, 0.0, 0.0)):
    """Create an independent copy of the captured limb; never read an existing rig."""
    import maya.cmds as c
    if not isinstance(namespace, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', namespace):
        raise ValueError('Invalid namespace')
    if len(offset) != 3 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in offset):
        raise ValueError('offset must contain three finite numbers')
    if c.currentUnit(q=True, linear=True) != 'cm' or c.currentUnit(q=True, angle=True) != 'deg':
        raise ValueError('This captured rig requires centimeters and degrees')
    if not c.pluginInfo('quatNodes', q=True, loaded=True):
        c.loadPlugin('quatNodes', quiet=True)
    spec = json.loads((DATA/'limb_v1.json').read_text(encoding='utf-8'))
    base, index = namespace, 2
    while c.namespace(exists=':'+namespace):
        namespace = '{}_{:02d}'.format(base, index)
        index += 1
    selection = c.ls(sl=True,long=True) or []
    previous_namespace = c.namespaceInfo(currentNamespace=True)
    frame = c.currentTime(q=True)
    undo = c.undoInfo(q=True,state=True)
    if undo: c.undoInfo(openChunk=True, chunkName='RebuildSoftLimb')
    try:
        c.namespace(setNamespace=':')
        c.namespace(add=namespace)
        from .native import create
        create(DATA/'limb_v1.ma', spec, namespace)
        c.namespace(setNamespace=':')
        names = [namespace+':'+n for n in spec['nodes']]
        from .easy_rig import create_recalculate_node
        names.append(create_recalculate_node(namespace))
        if any(not c.objExists(n) for n in names):
            raise RuntimeError('Incomplete limb template import')
        # Read every transform to force expression/constraint evaluation before moving the rig.
        error = 0.0
        for name, expected in spec['world_matrices'].items():
            actual = c.xform(namespace+':'+name,q=True,ws=True,m=True)
            error = max(error, max(abs(a-b) for a,b in zip(actual,expected)))
        if error > 1e-4:
            raise RuntimeError('Rebuilt pose differs from template: {}'.format(error))
        group = c.createNode('transform', name=namespace+':rig_root', skipSelect=True)
        for root in spec['roots']:
            c.parent(namespace+':'+root, group, relative=True)
        c.setAttr(group+'.translate', *offset)
        c.addAttr(group,ln='replicaVersion',dt='string')
        c.setAttr(group+'.replicaVersion',VERSION,type='string',lock=True)
        # Common offset must move every branch exactly once, including constrained roots.
        for name, expected in spec['world_matrices'].items():
            wanted = list(expected)
            wanted[12:15] = [a+b for a,b in zip(wanted[12:15],offset)]
            actual = c.xform(namespace+':'+name,q=True,ws=True,m=True)
            if max(abs(a-b) for a,b in zip(actual,wanted)) > 1e-4:
                raise RuntimeError('Offset changed internal rig pose: '+name)
        return {'namespace':namespace,'root':group,'version':VERSION,'nodes':names+[group],
                'baseline_max_error':error,'offset':list(offset),
                'controls':{key:namespace+':'+value for key,value in spec['controls'].items()},
                'joints':[namespace+':joint'+str(i) for i in (1,2,3)]}
    except Exception:
        # The namespace was absent before this call; cleanup cannot touch another rig.
        for n in reversed(c.ls(namespace+':*', long=True) or []):
            if c.objExists(n):
                c.delete(n)
        if c.namespace(exists=namespace): c.namespace(removeNamespace=namespace)
        raise
    finally:
        c.namespace(setNamespace=previous_namespace)
        if c.currentTime(q=True) != frame: c.currentTime(frame)
        c.select(selection,r=True) if selection else c.select(clear=True)
        if undo: c.undoInfo(closeChunk=True)
