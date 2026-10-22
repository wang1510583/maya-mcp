"""Route reverse-foot move gestures to the ankle's authored translation.

Only mouse gestures are routed. Existing curves and roll pivots are untouched;
playback still uses the native graph. Rotation gestures retain their old path.
"""
import json

ROLES = ('heel', 'toe_end', 'ball')


def key_plugs(controls):
    """Include the routed ankle when choosing the active animation layer."""
    import maya.cmds as c
    if c.contextInfo(c.currentCtx(),c=True) != 'manipMove':return []
    plugs=[]
    for control in controls:
        data=json.loads(c.getAttr(control+'.zeroChannelData'))
        if data['part'].startswith('leg_') and data['role'] in ROLES:
            foot=json.loads(c.getAttr(data['root']+'.zeroPartData'))['controls']['foot']
            plugs.extend(foot+'.translate'+a for a in 'XYZ')
    return list(dict.fromkeys(plugs))


def attach(entry, data, routes):
    import maya.cmds as c
    from . import live_edit
    if (entry['mode'] != 'manipMove' or not data['part'].startswith('leg_')
            or data['role'] not in ROLES + ('foot',)):
        return
    root = c.ls(data['root'], long=True)[0]
    if root in routes:
        entry['foot_move'] = routes[root]
        return
    # A selected ankle is processed first, and already owns its isolated TR.
    if data['role'] == 'foot':
        proxy, source = entry['proxy'], entry['source']
    else:
        proxy = json.loads(c.getAttr(root + '.zeroPartData'))['controls']['foot']
        source = json.loads(c.getAttr(proxy + '.zeroChannelData'))['source']
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
    routes[root] = route
    entry['foot_move'] = route


def update(entry, native):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from .live_edit import _frame
    route = entry['foot_move']
    if route['owner'] is not entry:
        # Multiple handles of one foot represent one move, never stacked deltas.
        return
    delta = om.MVector(*[v-start for v,start in zip(native[:3], entry['native_start'][:3])])
    delta *= entry['parent']
    source = route['source']
    desired = om.MVector(*route['position']) + delta
    actual = om.MVector(*list(_frame(source))[12:15])
    # Maya parentMatrix already includes offsetParentMatrix (also external
    # constraint input spaces); count it once, and retain existing rotations.
    local = (desired-actual) * om.MMatrix(c.getAttr(source+'.parentMatrix[0]')).inverse()
    for axis, value in zip('XYZ', local):
        plug = source+'.translate'+axis
        if abs(value)>1e-10:
            c.setAttr(plug, c.getAttr(plug)+value)
