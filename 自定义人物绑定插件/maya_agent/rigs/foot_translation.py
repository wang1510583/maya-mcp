"""Route reverse-foot translation to the ankle and bound authored move input.

Only mouse gestures are routed. Existing curves and roll pivots are untouched;
playback still uses the native graph. Heel/toe-end/ball rotation compensation also
uses ankle translation while retaining the selected pivot's rotation.
"""
from maya_agent.rigs import scene_data

ROLES = ('heel', 'toe_end', 'ball')
ROTATION_ROLES = ROLES


def key_plugs(controls):
    """Include the routed ankle when choosing the active animation layer."""
    import maya.cmds as c
    mode=c.contextInfo(c.currentCtx(),c=True)
    roles=ROLES if mode=='manipMove' else ROTATION_ROLES if mode=='manipRotate' else ()
    plugs=[]
    for control in controls:
        data=scene_data.read(control+'.zeroChannelData')
        if data['part'].startswith('leg_') and data['role'] in roles:
            foot=scene_data.read(data['root']+'.zeroPartData')['controls']['foot']
            plugs.extend(foot+'.translate'+a for a in 'XYZ')
    return list(dict.fromkeys(plugs))


def attach(entry, data, routes):
    import maya.cmds as c
    from . import live_edit
    moving=entry['mode']=='manipMove'
    rotating=entry['mode']=='manipRotate'
    roles=ROLES if moving else ROTATION_ROLES if rotating else ()
    if (not roles or not data['part'].startswith('leg_')
            or data['role'] not in roles + ('foot',)):
        return
    key='foot_move' if moving else 'foot_rotation'
    if rotating:entry['roll_translation']=list(c.getAttr(entry['source']+'.translate')[0])
    root = c.ls(data['root'], long=True)[0]
    if root in routes:
        entry[key] = routes[root]
        return
    # A selected ankle is processed first, and already owns its isolated TR.
    if data['role'] == 'foot':
        proxy, source = entry['proxy'], entry['source']
    else:
        proxy = scene_data.read(root + '.zeroPartData')['controls']['foot']
        source = scene_data.read(proxy + '.zeroChannelData')['source']
        if c.objExists(source + '.liveInput'):
            source = (c.listConnections(source + '.liveInput', s=True, d=False) or [source])[0]
        plugs = [proxy + '.translate' + axis for axis in 'XYZ']
        for p in plugs:
            if c.getAttr(p, lock=True):
                raise ValueError('脚腕位移已锁定，无法承接移动：' + p)
        snapshot = live_edit._snapshot(plugs)
        entry['snapshot'][0].update(snapshot[0])
        entry['snapshot'][1].update(snapshot[1])
        for p in plugs:
            dst = source + '.' + p.rsplit('.', 1)[1]
            edge = c.connectionInfo(dst, sfd=True)
            if not edge:
                raise ValueError('脚腕位移输入未连接：' + dst)
            value = c.getAttr(dst)
            c.disconnectAttr(edge, dst)
            c.setAttr(dst, value)
            entry['edges'].append((p, dst))
            entry['input_edges'][dst] = edge
            incoming = c.connectionInfo(p, sfd=True)
            if incoming:
                value = c.getAttr(p)
                c.disconnectAttr(incoming, p)
                c.setAttr(p, value)
                entry['curve_edges'].append((incoming, p))
    route = dict(owner=entry, source=source, proxy=proxy,
                 position=list(live_edit._frame(source))[12:15])
    # These are registered template nodes within this leg's own namespace.
    ns=root.rsplit('|',1)[-1].rsplit(':',1)[0]
    length=ns+':leng_base';limit=ns+':pivot_feet'
    if c.objExists(length) and c.objExists(limit):
        route['reach']=(length,limit)
    routes[root] = route
    entry[key] = route


def _translate(source,world_delta):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    local=world_delta*om.MMatrix(c.getAttr(source+'.parentMatrix[0]')).inverse()
    for axis,value in zip('XYZ',local):
        if abs(value)>1e-10:c.setAttr(source+'.translate'+axis,c.getAttr(source+'.translate'+axis)+value)


def transfer_rotation(entry):
    """Move only this gesture's roll compensation to the ankle, preserving pose.

    Moving the foot ancestor keeps the ankle input frame unchanged. Toe joint
    translation follows the solved ankle and only reads the toe input rotation;
    its displayed position also includes ball motion, so the two translation
    changes cancel there even though the raw toe input is a sibling of ball.
    Old authored roll translations are left unchanged.
    """
    import maya.cmds as c
    import maya.api.OpenMaya as om
    if entry['role'] not in ROTATION_ROLES:return
    source=entry['source'];base=entry['roll_translation']
    delta=om.MVector(*[v-b for v,b in zip(c.getAttr(source+'.translate')[0],base)])
    delta*=om.MMatrix(c.getAttr(source+'.parentMatrix[0]'))
    c.setAttr(source+'.translate',*base)
    _translate(entry['foot_rotation']['source'],delta)


def update(entry, native):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _frame
    route = entry['foot_move']
    if route['owner'] is not entry:
        # Multiple handles of one foot represent one move, never stacked deltas.
        if route.get('clamped'):_clamp_surface(entry)
        return
    delta = om.MVector(*[v-start for v,start in zip(native[:3], entry['native_start'][:3])])
    delta *= entry['parent']
    source = route['source']
    desired = om.MVector(*route['position']) + delta
    actual = om.MVector(*list(_frame(source))[12:15])
    # Maya parentMatrix already includes offsetParentMatrix (also external
    # constraint input spaces); count it once, and retain existing rotations.
    _translate(source,desired-actual)
    route['clamped']=False
    if 'reach' in route and delta.length()>1e-10:
        length,limit=route['reach']
        # Read the original solver's own capped distance, including its current
        # stretch settings. Do not infer a fixed XYZ limit or change the solver.
        excess=c.getAttr(length+'.translateX')-c.getAttr(limit+'.translateX')
        if excess>1e-8:
            correction=om.MVector(-excess,0,0)*om.MMatrix(c.getAttr(length+'.parentMatrix[0]'))
            _translate(source,correction)
            route['clamped']=True
            _clamp_surface(entry)


def _clamp_surface(entry):
    """Keep the editable temporary drag channels at the accepted input too."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _frame
    route=entry['foot_move']
    accepted=(om.MVector(*list(_frame(route['source']))[12:15])-om.MVector(*route['position']))*entry['parent'].inverse()
    for axis,start,value in zip('XYZ',entry['native_start'],accepted):
        c.setAttr(entry['proxy']+'.translate'+axis,start+value)
    entry['last_native']=[c.getAttr(entry['proxy']+'.'+a) for a in entry['native_attrs']]
