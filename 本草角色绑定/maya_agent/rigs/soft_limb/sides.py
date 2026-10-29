"""Finalize L/R names without mirroring or changing the selected target pose."""
import re


def validate(side):
    if side not in ('L', 'R'):
        raise ValueError('side 必须为 L（左侧）或 R（右侧）。')


def apply(rig, side, metadata_attr='armSide'):
    import maya.cmds as c
    validate(side)
    prefix = rig['namespace'] + ':'
    renames = {}
    if side == 'R':
        # Work only on this build's namespace, including its animation curves and shapes.
        # Explicitly rename shapes so automatic shape renaming cannot invalidate the map.
        for path in c.ls(prefix+'*', long=True) or []:
            name = path.split('|')[-1]
            leaf = name[len(prefix):]
            renamed = re.sub(r'_L(?=\d|_|Shape\d*$|$)', '_R', leaf)
            if renamed != leaf:
                renames[name] = prefix+renamed
        for old, new in renames.items():
            if c.objExists(new):
                raise RuntimeError('右侧名称已被占用：'+new)
        for old, new in renames.items():
            actual = c.rename(old, ':'+new, ignoreShape=True)
            if actual != new:
                raise RuntimeError('右侧节点重命名不一致：'+actual)

    def remap(value):
        if isinstance(value, str):
            if value in renames: return renames[value]
            if value.startswith('|'):
                return '|'.join(renames.get(part,part) for part in value.split('|'))
            return value
        if isinstance(value, list): return [remap(v) for v in value]
        if isinstance(value, dict): return {k:remap(v) for k,v in value.items()}
        return value

    updated = remap(rig)
    rig.clear()
    rig.update(updated)
    c.addAttr(rig['root'], longName=metadata_attr, dataType='string')
    c.setAttr(rig['root']+'.'+metadata_attr, side, type='string', lock=True)
    rig['side'] = side
