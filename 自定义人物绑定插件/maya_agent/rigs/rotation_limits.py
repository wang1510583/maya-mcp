"""Preserve limit settings while handing rotation to a constraint solver.

Euler-equivalent solutions must not be clipped independently on each axis.
Only driven targets are changed, after their original motion has been captured.
"""

ENABLES=tuple(bound+'Rot'+axis+'LimitEnable' for bound in ('min','max') for axis in 'XYZ')
VALUES=tuple(bound+'Rot'+axis+'Limit' for bound in ('min','max') for axis in 'XYZ')


def snapshot(node):
    import maya.cmds as c
    state={attr:c.getAttr(node+'.'+attr) for attr in ENABLES+VALUES}
    return state


def disable(samples):
    import maya.cmds as c
    for sample in samples:
        if 'rotation_limits' not in sample:
            sample['rotation_limits']=snapshot(sample['node'])
        for attr in ENABLES:
            plug=sample['node']+'.'+attr
            if c.getAttr(plug) and (c.getAttr(plug,lock=True) or c.connectionInfo(plug,sfd=True)):
                raise ValueError('旋转限幅开关已锁定或被驱动，无法安全接管：'+plug)
    for sample in samples:
        state=sample['rotation_limits']
        for attr in ENABLES:
            if state[attr]:c.setAttr(sample['node']+'.'+attr,False)
        # Limit flags do not consistently invalidate cached joint matrices.
        c.dgdirty(sample['node'],allPlugs=True)


def restore(samples):
    import maya.cmds as c
    for sample in samples:
        if not c.objExists(sample['node']):continue
        for attr,value in sample.get('rotation_limits',{}).items():
            if attr in ENABLES and c.getAttr(sample['node']+'.'+attr)!=value:
                c.setAttr(sample['node']+'.'+attr,value)
        c.dgdirty(sample['node'],allPlugs=True)


def record(samples):
    return {s['node']:s['rotation_limits'] for s in samples
            if 'rotation_limits' in s and any(s['rotation_limits'][a] for a in ENABLES)}
