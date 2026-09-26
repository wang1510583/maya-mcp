"""Hide known rig helpers in an owned display layer without changing rig logic."""
import re

OWNER='integratedDisplayOwner'


def collect(rig):
    import maya.cmds as c
    hidden=set();axes=set();protected=set()
    auxiliary_roles={'parameters','settings','end_locator','roll'}
    for part in rig['parts'].values():
        for role,node in part['controls'].items():
            if role not in auxiliary_roles and isinstance(node,str):protected.update(c.ls(node,long=True) or [])
        ns=part['namespace']+':'
        for node in c.ls(ns+'*',type='transform',long=True) or []:
            if c.nodeType(node) not in ('joint','transform'):continue
            name=node.rsplit('|',1)[-1].rsplit(':',1)[-1]
            if re.fullmatch(r'(?:strech_ik_(?:foot|knee)|knee_ctrl)\d+(?:_[LR]\d+)?',name):hidden.add(node)
            if re.fullmatch(r'(?:hand|ik_connect)_[LR]\d+',name):hidden.add(node)
            if name in ('shoulder_locator','hip_locator'):hidden.add(node)
            if re.fullmatch(r'base_[LR]\d+',name):axes.add(node)
            if name.startswith('rotator_null'):
                for shape in c.listRelatives(node,allDescendents=True,fullPath=True) or []:
                    if c.nodeType(shape) in ('nurbsCurve','locator'):hidden.add(shape)
    for suffix in ('outputs','reference_motion'):
        hidden.update(c.ls(rig['namespace']+':'+suffix,long=True) or [])
    # Hiding an ancestor would hide its animation controls too. If a future
    # template puts controls below a helper, hide only that helper's shapes.
    safe=set()
    for node in hidden:
        if node in protected:continue
        if any(p.startswith(node+'|') for p in protected):
            safe.update(c.listRelatives(node,shapes=True,fullPath=True) or [])
        else:safe.add(node)
    return dict(members=sorted(safe),axes=sorted(axes),protected=sorted(protected))


def apply(rig):
    """Idempotent; unrelated layers and source geometry are never removed."""
    import maya.cmds as c
    plan=collect(rig);owner=c.ls(rig['root'],uuid=True)[0]
    layer=next((n for n in c.ls(type='displayLayer') if c.attributeQuery(OWNER,node=n,exists=True)
                and c.getAttr(n+'.'+OWNER)==owner),None)
    if not layer:
        layer=c.createDisplayLayer(empty=True,makeCurrent=False)
        layer=c.rename(layer,rig['namespace']+':NoDisplay')
        c.addAttr(layer,ln=OWNER,dt='string');c.setAttr(layer+'.'+OWNER,owner,type='string',lock=True)
    if plan['members']:c.editDisplayLayerMembers(layer,plan['members'],noRecurse=True)
    c.setAttr(layer+'.visibility',False)
    skipped_axes=[]
    for node in plan['axes']:
        plug=node+'.displayLocalAxis'
        if c.getAttr(plug,settable=True):c.setAttr(plug,False)
        else:skipped_axes.append(node)
    return dict(layer=layer,members=plan['members'],axes_hidden=[n for n in plan['axes'] if n not in skipped_axes],
                skipped_axes=skipped_axes)
