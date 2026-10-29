"""Easy Rig recalculation metadata, separate from the limb evaluation graph."""

# Easy Rig deliberately uses visibility connections as node references.
# Capture the live pole in world space before moving its FK parents. The roll
# helper is a derived pose and can differ from the active solver's bend plane;
# using it for snapping feeds another pose back into the solver on every click.
RECALCULATE_GROUPS = (
    ('zero', ('hand_L1',)),
    ('translate_orient_pivot', ('base_L1', 'base_L2', 'base_L3', 'elb_L1')),
    ('to_pivot_translate_orient', ('shldrFK_L1', 'armFK_L1', 'handFK_L1', 'elb_L1')),
    ('animated_object', ('shldrFK_L1', 'armFK_L1', 'handFK_L1', 'elb_L1', 'hand_L1')),
)


def create_recalculate_node(namespace):
    """Provide the discovery node expected by kurok_recalculate_system(0)."""
    import maya.cmds as c
    prefix = ':' + namespace.strip(':') + ':'
    name = prefix + 'recalculate_node'
    if c.objExists(name):
        raise ValueError('Recalculation metadata already exists: ' + name)
    for _, nodes in RECALCULATE_GROUPS:
        for node in nodes:
            if not c.objExists(prefix + node):
                raise ValueError('Missing recalculation target: ' + prefix + node)
    created = c.createNode('blindDataTemplate', name=name, skipSelect=True)
    for role, nodes in RECALCULATE_GROUPS:
        for index, node in enumerate(nodes):
            attribute = '{}{}'.format(role, index)
            c.addAttr(created, longName=attribute, shortName=attribute, attributeType='long')
            c.setAttr(created + '.' + attribute, channelBox=True)
            c.connectAttr(prefix + node + '.visibility', created + '.' + attribute)
    return created


def repair_recalculate_node(namespace):
    """Upgrade only our generated arm, retaining curves, pose and the roll graph."""
    import maya.cmds as c
    prefix=namespace.strip(':')+':'
    root=prefix+'rig_root'
    if not c.objExists(root+'.armSide') or not c.objExists(root+'.armTargets'):
        raise ValueError('仅修复本插件按选择创建的手臂：'+namespace)
    side=c.getAttr(root+'.armSide')
    if side not in ('L','R'):raise ValueError('手臂侧别元数据无效：'+namespace)
    registry=prefix+'recalculate_node'
    plug=registry+'.translate_orient_pivot3'
    pole=prefix+'elb_'+side+'1'
    if not c.objExists(plug) or not c.objExists(pole):raise ValueError('手臂对齐登记不完整：'+namespace)
    expected=c.connectionInfo(registry+'.to_pivot_translate_orient3',sourceFromDestination=True)
    if expected!=pole+'.visibility':raise ValueError('手臂肘部对齐目标已被自定义，未改动：'+namespace)
    old=c.connectionInfo(plug,sourceFromDestination=True)
    if old not in (prefix+'locator3.visibility',pole+'.visibility'):
        raise ValueError('手臂肘部对齐参考已被自定义，未改动：'+namespace)
    if old!=pole+'.visibility':c.connectAttr(pole+'.visibility',plug,force=True)
    if not c.objExists(root+'.alignmentVersion'):c.addAttr(root,ln='alignmentVersion',dt='string')
    c.setAttr(root+'.alignmentVersion','1.1.0',type='string')
    return dict(namespace=namespace,changed=old!=pole+'.visibility',old_reference=old,pole_reference=pole)
