"""Reversible, per-character box previews driven by the existing rig."""
import re
from statistics import median

from maya_agent.rigs import scene_data
from . import PARTS

# Width and depth measured from the reference boxes, in common model units.
# The body profile runs from the pelvis to the chest.
_BODY_PROFILE = ((2.09, 1.32), (1.79, 1.03), (1.79, 1.03), (1.92, 1.32))
_CROSS_SECTIONS = {
    'head': ((.60, .60), (1.00, 1.00)),
    'shoulder': ((.34575, .59735),),
    'arm': ((.69, .92), (.50049, .70803), (.28926, .58920)),
    'leg': ((.94, .92), (.72601, .77219), (.73699, .756), (.73699, .54)),
}
_LENGTH_REFERENCES = {'arm': (1.65, 1.65), 'leg': (2.05, 1.99)}
# Per chain in rig order: middle thickness, tip length, tip thickness,
# and tip center shift relative to the original tip box length.
_FINGER_PROFILE = (
    (1.519872, 1.437585, 1.834815, .517492),
    (1.519872, 1.437585, 1.834815, .455289),
    (1.519872, 1.437585, 1.834815, .382050),
    (1.667393, 1.566432, 2.170796, .488309),
    (1.390985, 1.302608, 1.736231, .479335),
)
_PROFILE_VERSION = 6
_COLOR_LINK = '.boxPreviewShadingGroup'


def _path(c, node):
    matches = c.ls(node, long=True) if node else []
    return matches[0] if matches and len(matches) == 1 else None


def _preview_groups(c, root):
    return [plug.rsplit('.', 1)[0] for plug in c.listConnections(
        root + '.message', source=False, destination=True, plugs=True) or []
        if plug.endswith('.boxPreviewOwner')]


def _preview_group(c, root):
    groups = _preview_groups(c, root)
    if len(groups) > 1:
        raise ValueError('此角色有多个 Box 简模组，请先整理场景中的重复组。')
    return _path(c, groups[0]) if groups else None


def _selected(c):
    selection = c.ls(selection=True, long=True, objectsOnly=True) or []
    if not selection:
        raise ValueError('请先选择一套集成绑定的控制器或角色根组。')
    matches = []
    for root in c.ls('::*.integratedRigData', objectsOnly=True, long=True) or []:
        rig = scene_data.read(root + '.integratedRigData')
        containers = {_path(c, part.get('root')) for part in rig['parts'].values()}
        containers.update(_path(c, group) for group in _preview_groups(c, root))
        containers.add(root)
        if any(node == owner or node.startswith(owner + '|')
               for node in selection for owner in containers if owner):
            matches.append((root, rig))
    if len(matches) != 1:
        raise ValueError('请选择同一套集成绑定中的控制器或角色根组。')
    return matches[0]


def _chains(part, kind):
    mappings = part.get('target_mapping', [])
    if not mappings and kind in ('arm', 'leg'):
        mappings = [dict(target=joint, driver=joint) for joint in part.get('joints', [])]
    if kind == 'hand':
        offset = 0
        for chain in part.get('chains', []):
            yield mappings[offset:offset + len(chain)]
            offset += len(chain)
    else:
        yield mappings


def _segments(c, om, rig):
    parts = rig['parts']
    for key, part in parts.items():
        if key not in PARTS:
            continue
        kind = PARTS[key]['kind']
        for chain_index, chain in enumerate(_chains(part, kind)):
            rows = []
            for index, mapping in enumerate(chain):
                # The solved limb joints follow all IK/FK modes, including pole
                # and foot pivot edits. Other parts use their own controls.
                driver = mapping.get('driver') if kind in ('arm', 'leg') else (
                    mapping.get('control') or mapping.get('driver'))
                driver = _path(c, driver or mapping.get('joint'))
                target = _path(c, mapping.get('target'))
                if not driver or not target:
                    continue
                matrix = om.MMatrix(c.getAttr(driver + '.worldMatrix[0]'))
                point = om.MVector(c.getAttr(target + '.worldMatrix[0]')[12:15])
                rows.append((index, driver, matrix, point))
            for slot, (index, driver, matrix, point) in enumerate(rows):
                previous = rows[slot - 1][3] if slot else None
                following = rows[slot + 1][3] if slot + 1 < len(rows) else None
                if kind == 'shoulder' and following is None:
                    arm = parts.get('arm_' + PARTS[key]['side'], {})
                    arm_targets = arm.get('target_mapping', [])
                    target = _path(c, arm_targets[0]['target']) if arm_targets else None
                    if target:
                        following = om.MVector(c.getAttr(target + '.worldMatrix[0]')[12:15])
                yield key, kind, index, driver, matrix, point, previous, following, len(chain), chain_index


def _profile_scale(segments):
    ratios = []
    torso = []
    for _, kind, index, _, _, point, _, following, _, _ in segments:
        if following is None:
            continue
        length = (following - point).length()
        if length < 1e-6:
            continue
        if kind in _LENGTH_REFERENCES and index < 2:
            ratios.append(length / _LENGTH_REFERENCES[kind][index])
        if kind == 'body':
            torso.append(length)
    if ratios:
        return median(ratios)
    if torso:
        # Spine targets span the interior of the reference torso.
        return sum(torso) / 2.45
    neck = next(((row[7] - row[5]).length() for row in segments
                 if row[1] == 'head' and row[7] is not None), 0)
    if neck > 1e-6:
        return neck / .36
    lengths = [(row[7] - row[5]).length() for row in segments if row[7] is not None]
    length = median(lengths) if lengths else 0
    return length / .55 if length > 1e-6 else 1.0


def _cross_section(kind, index, count, terminal):
    if kind == 'body':
        if count == 1:
            return _BODY_PROFILE[0]
        position = index * (len(_BODY_PROFILE) - 1) / (count - 1)
        lower = int(position)
        a = _BODY_PROFILE[lower]
        b = _BODY_PROFILE[min(lower + 1, len(_BODY_PROFILE) - 1)]
        return tuple(x + (y - x) * (position - lower) for x, y in zip(a, b))
    if kind == 'head':
        return _CROSS_SECTIONS[kind][int(terminal)]
    sections = _CROSS_SECTIONS[kind]
    return sections[min(index, len(sections) - 1)]


def _character_axes(c, om, segments):
    up = om.MVector(0, 0, 1) if c.upAxis(q=True, axis=True) == 'z' else om.MVector(0, 1, 0)
    anchors = {row[0]: row[5] for row in segments if row[2] == 0}
    lateral = next((anchors[part + '_L'] - anchors[part + '_R']
                    for part in ('shoulder', 'arm', 'leg')
                    if part + '_L' in anchors and part + '_R' in anchors), om.MVector(1, 0, 0))
    forward = lateral ^ up
    return up, forward.normal()


def _finger_shape(chain_index, index, terminal):
    if chain_index < len(_FINGER_PROFILE):
        middle, tip_length, tip_thickness, tip_shift = _FINGER_PROFILE[chain_index]
        if index == 1 and not terminal:
            return 1.0, middle, 0.0
        if index >= 2 and terminal:
            return tip_length, tip_thickness, tip_shift
    return 1.0, 1.0, 0.0


def _ground_plane(c, om, rig):
    master = _path(c, rig.get('master_control'))
    if master:
        matrix = c.getAttr(master + '.worldMatrix[0]')
        # The total control ring lies in its local XZ plane.
        normal = (om.MVector(matrix[8:11]) ^ om.MVector(matrix[:3])).normal()
        if normal.length() > 1e-6:
            return om.MVector(matrix[12:15]), normal
    return None


def _fit_ground(center, axes, dimensions, ground):
    origin, normal = ground
    half_extent = sum(abs(axis * normal) * size * .5 for axis, size in zip(axes, dimensions))
    clearance = (center - origin) * normal - half_extent
    return center + normal * max(0.0, -clearance)


def _box(c, om, group, segment, scale, up_axis, forward, ground=None):
    key, kind, index, driver, matrix, point, previous, following, count, chain_index = segment
    foot = kind == 'leg' and index >= 2
    direction = (following - point if following is not None else
                 point - previous if previous is not None else om.MVector(list(matrix)[:3]))
    if foot:
        direction -= up_axis * (direction * up_axis)
    length = direction.length()
    if length < 1e-6:
        direction = om.MVector(list(matrix)[:3])
    if direction.length() < 1e-6:
        direction = om.MVector(1, 0, 0)
    axis = direction.normal()
    if length < 1e-6 or (following is None and previous is None):
        length = scale * .80
    if following is None:
        terminal_lengths = {'body': 1.31, 'head': 1.00, 'arm': .68, 'leg': .45, 'shoulder': .72}
        length = terminal_lengths[kind] * scale if kind in terminal_lengths else length * .65
    length_factor = 1.0
    finger_shift = 0.0
    if kind == 'hand':
        length_factor, thickness, finger_shift = _finger_shape(chain_index, index, following is None)
        width = depth = length * .55 * thickness
    else:
        width, depth = (value * scale for value in _cross_section(kind, index, count, following is None))
    center = point + axis * (length * ((.25 if following is None else .5) + .94 * finger_shift))
    if foot and following is not None:
        center += up_axis * ((following - point) * up_axis)
    depth_hint = up_axis if foot else forward
    up = (depth_hint ^ axis).normal()
    if up.length() < 1e-6:
        up = om.MVector(list(matrix)[4:7]).normal()
    if abs(axis * up) > .95 or up.length() < 1e-6:
        up = min((om.MVector(1, 0, 0), om.MVector(0, 1, 0), om.MVector(0, 0, 1)),
                 key=lambda vector: abs(axis * vector))
    cross = (axis ^ up).normal()
    up = cross ^ axis
    if foot and index == 2:
        # The edited foot extends back from its original center and sits higher.
        center += (axis * -.264971 + cross * .106137) * scale
    # Resize around the original box center, matching the edited reference.
    if kind == 'shoulder':
        length_factor = .84729
    if kind == 'arm' and index == 2 and following is None:
        length_factor = .56592 / .68
    if foot and index == 2:
        length_factor = 1.705068
    sizes = (length * .94 * length_factor, width, depth)
    if foot and ground is not None:
        center = _fit_ground(center, (axis, up, cross), sizes, ground)
    world = om.MMatrix([*axis, 0, *up, 0, *cross, 0, *center, 1])
    dimensions = [om.MDistance.internalToUI(value) for value in sizes]
    follower = c.createNode('transform', name=key + '_boxFollow', parent=group)
    c.setAttr(follower + '.inheritsTransform', False)
    cube = c.polyCube(name=key + '_box%02d' % (index + 1), width=dimensions[0],
                      height=dimensions[1], depth=dimensions[2], constructionHistory=False)[0]
    try:
        cube = c.parent(cube, follower, relative=True)[0]
    except Exception:
        c.delete(cube)
        raise
    c.setAttr(cube + '.offsetParentMatrix', *list(world * matrix.inverse()), type='matrix')
    c.connectAttr(driver + '.worldMatrix[0]', follower + '.offsetParentMatrix')
    if kind == 'head' and following is None:
        _eyes(c, cube, *dimensions)


def _eyes(c, head, length, width, depth):
    # Head-local X runs from neck to crown; +Z faces forward.
    radius = min(length, width, depth) * .105
    for side, sign in (('L', 1), ('R', -1)):
        eye = c.polySphere(name='boxEye_' + side, radius=radius, subdivisionsX=12,
                           subdivisionsY=8, constructionHistory=False)[0]
        try:
            eye = c.parent(eye, head, relative=True)[0]
        except Exception:
            c.delete(eye)
            raise
        c.setAttr(eye + '.translate', length * .16, sign * width * .23, depth * .5)


def _shading_group(c, group):
    plug = group + _COLOR_LINK
    return c.connectionInfo(plug, sourceFromDestination=True).rsplit('.', 1)[0] if c.objExists(plug) else ''


def _assign_color(c, group, shading_group):
    meshes = [shape for shape in c.listRelatives(group, allDescendents=True, fullPath=True, type='mesh') or []
              if not shape.split('|')[-2].rsplit(':', 1)[-1].startswith('boxEye_')]
    if not meshes:
        raise ValueError('这套简模没有可着色的 Box。')
    c.sets(meshes, edit=True, forceElement=shading_group)
    plug = group + _COLOR_LINK
    if not c.objExists(plug):
        c.addAttr(group, longName=_COLOR_LINK[1:], attributeType='message')
    if not c.connectionInfo(plug, isDestination=True):
        c.connectAttr(shading_group + '.message', plug)


def choose_selected_color():
    import maya.cmds as c

    root, _ = _selected(c)
    group = _preview_group(c, root)
    if not group:
        raise ValueError('请先点击「添加box简模」为这个角色生成简模。')
    shading_group = _shading_group(c, group)
    source = c.connectionInfo(shading_group + '.surfaceShader', sourceFromDestination=True) if shading_group else ''
    material = source.rsplit('.', 1)[0]
    current = c.getAttr(material + '.color')[0] if material else (.5, .5, .5)
    c.colorEditor(rgbValue=current)
    if not c.colorEditor(query=True, result=True):
        return None
    rgb = c.colorEditor(query=True, rgbValue=True)
    created = []
    c.undoInfo(openChunk=True, chunkName='ColorCharacterBoxPreview')
    try:
        label = group.rsplit('|', 1)[-1]
        new_shading_group = not shading_group
        if not material:
            material = c.shadingNode('lambert', asShader=True, name=label + '_color')
            created.append(material)
        if new_shading_group:
            shading_group = c.sets(renderable=True, noSurfaceShader=True, empty=True, name=label + '_colorSG')
            created.append(shading_group)
        if not source:
            c.connectAttr(material + '.outColor', shading_group + '.surfaceShader')
        if new_shading_group:
            _assign_color(c, group, shading_group)
        c.setAttr(material + '.color', *rgb, type='double3')
    except Exception:
        if created:
            c.delete(created)
        raise
    finally:
        c.undoInfo(closeChunk=True)
    return rgb


def _character_meshes(c, rig):
    targets = set()
    for part in rig['parts'].values():
        rows = part.get('original_target_mapping') or part.get('target_mapping', [])
        targets.update(_path(c, row.get('target')) for row in rows)
    skins = {skin for target in targets if target
             for skin in c.listConnections(target + '.worldMatrix[0]', source=False,
                                           destination=True, type='skinCluster') or []}
    meshes = set()
    for skin in skins:
        for shape in c.skinCluster(skin, query=True, geometry=True) or []:
            shape = _path(c, shape)
            if shape and c.nodeType(shape) == 'mesh' and not c.getAttr(shape + '.intermediateObject'):
                meshes.add(shape)
    return sorted(meshes)


def _visible_meshes(c, group, rig, enable):
    """Remember exactly the shapes hidden by this preview, using persistent links."""
    registry = group + '.boxPreviewHiddenMesh'
    saved = []
    for index in c.getAttr(registry, multiIndices=True) or []:
        destination = '%s[%d]' % (registry, index)
        source = c.connectionInfo(destination, sourceFromDestination=True)
        if source:
            saved.append((source, destination))
    if enable:
        meshes = _character_meshes(c, rig)
        pairs = [(shape + '.message', '%s[%d]' % (registry, index))
                 for index, shape in enumerate(meshes)
                 if c.getAttr(shape + '.visibility') and
                 c.getAttr(shape + '.visibility', settable=True) and
                 not c.connectionInfo(shape + '.visibility', isDestination=True)]
        skipped = sum(bool(c.getAttr(shape + '.visibility')) for shape in meshes) - len(pairs)
    else:
        pairs, skipped = saved, 0
    changed = []
    try:
        for source, destination in pairs:
            visibility = source.rsplit('.', 1)[0] + '.visibility'
            if (not c.getAttr(visibility, settable=True) or
                    c.connectionInfo(visibility, isDestination=True)):
                raise ValueError('原模型可见性已被锁定或连接：' + visibility)
            original = c.getAttr(visibility)
            if enable:
                c.connectAttr(source, destination)
            else:
                c.disconnectAttr(source, destination)
            changed.append((source, destination, visibility, original))
            c.setAttr(visibility, not enable)
        c.setAttr(group + '.visibility', enable)
    except Exception:
        for source, destination, visibility, original in reversed(changed):
            if enable:
                c.disconnectAttr(source, destination)
            else:
                c.connectAttr(source, destination)
            if c.getAttr(visibility) != original:
                c.setAttr(visibility, original)
        raise
    return skipped


def add_selected():
    return _set_preview(add=True)


def toggle_selected():
    return _set_preview(add=False)


def _set_preview(add):
    import maya.cmds as c
    import maya.api.OpenMaya as om

    root, rig = _selected(c)
    selection = c.ls(selection=True, long=True) or []
    group = _preview_group(c, root)
    if not group and not add:
        raise ValueError('请先点击「添加box简模」为这个角色生成简模。')
    if group and add and c.getAttr(group + '.visibility'):
        return dict(enabled=True, group=group, skipped_meshes=0)
    created = None
    old_group = None
    c.undoInfo(openChunk=True, chunkName='ToggleCharacterBoxPreview')
    try:
        if group and not c.getAttr(group + '.visibility'):
            version = group + '.boxPreviewProfile'
            if not c.objExists(version) or c.getAttr(version) != _PROFILE_VERSION:
                old_group, group = group, None
        if group is None:
            segments = list(_segments(c, om, rig))
            if not segments:
                raise ValueError('所选角色没有可用于创建 Box 简模的部位。')
            scale = _profile_scale(segments)
            up_axis, forward = _character_axes(c, om, segments)
            ground = _ground_plane(c, om, rig)
            label = re.sub(r'[^\w]', '_', root.rsplit('|', 1)[-1])
            created = c.createNode('transform', name=':' + label + '_boxPreview')
            group = _path(c, created)
            c.addAttr(group, longName='boxPreviewOwner', attributeType='message')
            c.addAttr(group, longName='boxPreviewHiddenMesh', attributeType='message', multi=True)
            c.addAttr(group, longName='boxPreviewProfile', attributeType='long', defaultValue=_PROFILE_VERSION)
            c.connectAttr(root + '.message', group + '.boxPreviewOwner')
            c.setAttr(group + '.visibility', False)
            for segment in segments:
                _box(c, om, group, segment, scale, up_axis, forward, ground)
            shading_group = _shading_group(c, old_group) if old_group else ''
            if shading_group:
                _assign_color(c, group, shading_group)
        enabled = not c.getAttr(group + '.visibility')
        skipped = _visible_meshes(c, group, rig, enabled)
        if old_group:
            try:
                c.delete(old_group)
            except Exception:
                _visible_meshes(c, group, rig, False)
                raise
        return dict(enabled=enabled, group=group, skipped_meshes=skipped)
    except Exception:
        if created:
            c.delete(created)
        raise
    finally:
        try:
            c.select([node for node in selection if c.objExists(node)] or [root], replace=True)
        finally:
            c.undoInfo(closeChunk=True)
