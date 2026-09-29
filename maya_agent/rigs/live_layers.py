"""Maya animation-layer routing for live gestures; never flattens a layer stack."""


def blend_nodes():
    import maya.cmds as c
    return {node for layer in c.ls(type='animLayer') or []
            for node in c.animLayer(layer,q=True,blendNodes=True) or []}


def curves_for_plug(plug,registered=None):
    """Accept time curves and registered layer blends, but not arbitrary drivers."""
    import maya.cmds as c
    registered=blend_nodes() if registered is None else registered
    curves=set();visited=set()
    def walk(destination):
        source=c.connectionInfo(destination,sourceFromDestination=True)
        if not source:return
        node=source.split('.')[0]
        if node in visited:return
        visited.add(node);kind=c.nodeType(node)
        if kind.startswith('animCurveT'):
            curves.add(node);return
        if kind=='unitConversion':walk(node+'.input');return
        if node not in registered or not kind.startswith('animBlendNode'):
            raise ValueError('实时操作不覆盖外部驱动：'+plug)
        for attr in ('inputA','inputB'):
            children=c.attributeQuery(attr,node=node,listChildren=True) or [attr]
            for child in children:walk(node+'.'+child)
    walk(plug)
    return curves


def edit_layer(roots=()):
    """Honor the layer editor's selected/preferred layer, including BaseAnimation."""
    import maya.cmds as c
    import json
    layers=c.ls(type='animLayer') or []
    if len(layers)<2:return None
    if roots:
        plugs=[e['proxy'] for root in roots if c.objExists(root+'.liveAlignmentData') for e in json.loads(c.getAttr(root+'.liveAlignmentData'))['entries']]
        from . import arm_ik_shared,arm_ik
        for root in roots:
            if arm_ik_shared.active(root):
                plugs.extend(arm_ik._data(root)['controls']['wrist']+'.'+a for a in arm_ik.TR)
            if arm_ik_shared.active(root,'pole_locator'):
                plugs.extend(arm_ik._data(root)['controls']['pole']+'.translate'+a for a in 'XYZ')
        plugs.extend(n+'.'+a for n in c.ls(sl=True,long=True,objectsOnly=True) or []
                     for a in ('translateX','translateY','translateZ','rotateX','rotateY','rotateZ') if c.objExists(n+'.'+a))
        registered=blend_nodes()
        if not any(c.connectionInfo(p,sourceFromDestination=True).split('.')[0] in registered for p in plugs):
            return None
    selected=[l for l in layers if c.animLayer(l,q=True,selected=True)]
    preferred=[l for l in selected if c.animLayer(l,q=True,preferred=True)]
    candidates=preferred or selected
    if not candidates:
        for node in c.ls(sl=True,long=True,objectsOnly=True) or []:
            for attr in ('rotateX','translateX'):
                if c.objExists(node+'.'+attr):
                    layer=c.animLayer(node+'.'+attr,q=True,bestLayer=True)
                    if layer:candidates.append(layer)
    layer=candidates[0] if candidates else c.animLayer(q=True,root=True)
    if c.animLayer(layer,q=True,lock=True):raise ValueError('当前动画层已锁定，请解锁或选择可编辑层：'+layer)
    if c.animLayer(layer,q=True,mute=True) or c.animLayer(layer,q=True,weight=True)<=1e-8:
        raise ValueError('当前动画层未生效，请取消静音并设置非零权重：'+layer)
    return layer


def commit(layer,snapshots,auto,force_plugs=()):
    """Key final composite values through Maya's native layer value resolver.

    Calibration companions join the same layer only if they actually changed.
    Capture all final values before adding membership or evaluating any curves.
    """
    import maya.cmds as c
    before={p:v for values,curves in snapshots for p,v in values.items()}
    final={p:c.getAttr(p) for p in before}
    changed=[p for p in final if abs(final[p]-before[p])>1e-8]
    changed=list(dict.fromkeys(changed+[p for p in force_plugs if p in final]))
    if not changed:return
    root=c.animLayer(q=True,root=True)
    if layer!=root:
        # Build layer inputs from the pre-gesture value, not an unkeyed edited
        # constant, so muting/removing the layer restores the original base.
        for p,v in before.items():c.setAttr(p,v)
        members=set(c.animLayer(layer,q=True,attribute=True) or [])
        missing=[p for p in changed if p not in members and p.rsplit('|',1)[-1] not in members]
        if missing:c.animLayer(layer,e=True,attribute=missing)
        for p,v in final.items():c.setAttr(p,v)
    if auto:
        # Key vector rotations together. Maya resolves additive/override weights
        # and rotation accumulation; writing total Euler values into layer curves
        # directly would double the base pose or corrupt quaternion blending.
        groups={}
        for p in changed:
            node,attr=p.rsplit('.',1)
            attrs=groups.setdefault(node,set());attrs.add(attr)
            if attr.startswith('rotate'):
                attrs.update('rotate'+axis for axis in 'XYZ' if node+'.rotate'+axis in final)
        for node,attrs in groups.items():
            for p,v in final.items():c.setAttr(p,v)
            c.setKeyframe(node,attribute=sorted(attrs),animLayer=layer)
    for p,v in final.items():c.setAttr(p,v)


def key_mode_switch(snapshot,plug,force_plugs=()):
    """Record matched pose and stepped mode only at the current frame."""
    import maya.cmds as c
    from .zero_channels import resolve
    force_plugs=[resolve(p) for p in force_plugs]
    layer=edit_layer();final={p:c.getAttr(p) for p in snapshot[0]}
    force=set(force_plugs)|{plug}
    if layer:commit(layer,[snapshot],True,force_plugs=force)
    else:
        for p,v in final.items():
            if p in force or abs(v-snapshot[0][p])>1e-8:c.setKeyframe(p,v=v)
    curve=c.animLayer(layer,q=True,findCurveForPlug=plug) if layer else c.listConnections(plug,s=True,d=False,type='animCurve')
    if curve:c.keyTangent(curve,e=True,ott='step')
    for p,v in final.items():c.setAttr(p,v)
