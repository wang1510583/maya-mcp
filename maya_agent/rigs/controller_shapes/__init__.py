"""Packaged, pivot-relative controller artwork; never modifies rig transforms."""
import json
import math
from pathlib import Path

VERSION = '1.0.1'
DATA = Path(__file__).parent / 'data' / 'controller_shapes_v1.json'
HELPERS = {'parameters', 'settings', 'roll', 'end_locator'}
DISPLAY = ('overrideEnabled', 'overrideRGBColors', 'overrideColor',
           'overrideColorRGB', 'lineWidth')


def measure(key, targets):
    """World-space chain lengths, independent of character location or bent height."""
    import maya.cmds as c
    points = [c.xform(n, q=True, ws=True, rp=True) for n in targets]
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    method = 'chain_lengths'
    if not lengths:
        children = c.listRelatives(targets[0], children=True, type='joint', fullPath=True) or []
        parents = c.listRelatives(targets[0], parent=True, fullPath=True) or []
        neighbours = children or parents
        length = math.dist(points[0], c.xform(neighbours[0], q=True, ws=True, rp=True)) if neighbours else 0
        method = 'child_distance' if children else 'parent_distance'
        if length < 1e-5:
            bounds = c.exactWorldBoundingBox(targets[0])
            length = max(bounds[i+3]-bounds[i] for i in range(3))
            method = 'object_bounds'
        if length < 1e-5:
            # An isolated empty transform has no physical extent to measure.
            import maya.api.OpenMaya as om
            scale = om.MTransformationMatrix(om.MMatrix(c.xform(targets[0], q=True, ws=True, m=True))).scale(om.MSpace.kWorld)
            return dict(lengths=[], fallback_scale=abs(scale[0]), method='transform_scale')
        lengths = [length]
    return dict(lengths=lengths, method=method)


def _size(key, role, metrics):
    lengths = metrics['lengths']
    if not lengths:
        return None
    if key.startswith('arm'):
        if role == 'shoulder_fk': return lengths[0]
        if role in ('middle_fk', 'end_fk'): return lengths[-1]
    if key.startswith('leg'):
        return sum(lengths[:2]) if role in ('hip', 'knee') else lengths[-1]
    return sum(lengths)


def _display(node):
    import maya.cmds as c
    # Transform getAttr can resolve lineWidth on child shapes and return an
    # array. Store line width on each shape, not as a transform attribute.
    return {a: c.getAttr(node+'.'+a) for a in DISPLAY
            if c.attributeQuery(a,node=node,exists=True)}


def _set_display(node, attrs):
    import maya.cmds as c
    for attr, value in attrs.items():
        if not c.objExists(node+'.'+attr): continue
        if isinstance(value, (list, tuple)):
            c.setAttr(node+'.'+attr, *value[0])
        else:
            c.setAttr(node+'.'+attr, value)


def capture_control(node):
    """Read artwork only. CV offsets are relative to the actual rotation pivot."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    matrix = om.MMatrix(c.xform(node, q=True, ws=True, m=True))
    scale = om.MTransformationMatrix(matrix).scale(om.MSpace.kWorld)
    pivot = c.xform(node, q=True, os=True, rp=True)
    shapes = []
    for shape in c.listRelatives(node, shapes=True, fullPath=True) or []:
        kind = c.nodeType(shape)
        if kind not in ('nurbsCurve', 'locator'): continue
        # Retained solver shapes are not artwork. Recapturing a newly built rig
        # must not resurrect these hidden originals in subsequent creations.
        if not c.getAttr(shape+'.lodVisibility'): continue
        item = dict(type=kind, display=_display(shape), visibility=c.getAttr(shape+'.visibility'))
        if kind == 'nurbsCurve':
            selection = om.MSelectionList(); selection.add(shape)
            fn = om.MFnNurbsCurve(selection.getDagPath(0))
            item.update(degree=fn.degree, form=fn.form, knots=list(fn.knots()),
                        points=[[(p[i]-pivot[i])*scale[i] for i in range(3)]+[p.w]
                                for p in fn.cvPositions(om.MSpace.kObject)])
        else:
            position = c.getAttr(shape+'.localPosition')[0]
            item.update(position=[(position[i]-pivot[i])*scale[i] for i in range(3)],
                        size=[v*abs(scale[i]) for i,v in enumerate(c.getAttr(shape+'.localScale')[0])])
        shapes.append(item)
    result = dict(shapes=shapes, display=_display(node))
    if c.nodeType(node) == 'joint':
        result['joint'] = dict(drawStyle=c.getAttr(node+'.drawStyle'), radius=c.getAttr(node+'.radius')*abs(scale[0]))
    return result


def capture(rig, path):
    """Explicit authoring command; writes JSON only, never changes the source scene."""
    parts = {}
    for key, part in rig['parts'].items():
        targets = [m['target'] for m in part['original_target_mapping']]
        parts[key] = dict(metrics=measure(key, targets),
                          controls={role: capture_control(node) for role,node in part['controls'].items()
                                    if role not in HELPERS})
    data = dict(schema_version=1, version=VERSION, linear_unit='cm', parts=parts)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def _role(role, roles, current_roles):
    # Resample variable-count chains by normalized order, keeping both endpoints.
    for prefix in ('spine', 'neck'):
        if role.startswith(prefix):
            source = sorted(r for r in roles if r.startswith(prefix))
            target = sorted((r for r in current_roles if r.startswith(prefix)),
                            key=lambda r: int(r[len(prefix):]))
            if source:
                index = target.index(role)
                return source[round(index*(len(source)-1)/max(len(target)-1, 1))]
    return role


def apply(rig, key, targets=None, metrics=None, multiplier=1.0, created=None):
    """Apply only to a newly constructed part, retaining solver/Easy Rig shape nodes."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    template = json.loads(DATA.read_text(encoding='utf-8'))
    source = template['parts'][key]
    metrics = metrics or measure(key, targets or rig['joints'])
    selection = c.ls(sl=True, long=True) or []
    old_auto = c.autoKeyframe(q=True, state=True)
    new_nodes = []; report = {}
    try:
        c.autoKeyframe(state=False)
        for role, node in rig['controls'].items():
            if role in HELPERS: continue
            source_role = _role(role, source['controls'], rig['controls'])
            if source_role not in source['controls']: continue
            artwork = source['controls'][source_role]
            actual = _size(key, role, metrics)
            reference = _size(key, source_role, source['metrics'])
            factor = (actual/reference if actual is not None else metrics['fallback_scale'])*multiplier
            if not math.isfinite(factor) or factor <= 0: raise ValueError('控制器尺寸比例无效。')
            matrix = om.MMatrix(c.xform(node, q=True, ws=True, m=True))
            scale = om.MTransformationMatrix(matrix).scale(om.MSpace.kWorld)
            pivot = c.xform(node, q=True, os=True, rp=True)
            # Original locators can feed worldPosition into solvers. Keep their
            # identities/connections and hide only their drawing, never transforms.
            for shape in c.listRelatives(node, shapes=True, fullPath=True) or []:
                if c.nodeType(shape) in ('nurbsCurve', 'locator'):
                    c.setAttr(shape+'.lodVisibility', False)
            _set_display(node, artwork['display'])
            if 'joint' in artwork and c.nodeType(node) == 'joint':
                c.setAttr(node+'.drawStyle', artwork['joint']['drawStyle'])
                c.setAttr(node+'.radius', artwork['joint']['radius']*factor/abs(scale[0]))
            shapes = []
            for index, item in enumerate(artwork['shapes']):
                name = node.rsplit('|', 1)[-1]+'_artShape'+str(index)
                if item['type'] == 'nurbsCurve':
                    points = [tuple(pivot[i]+p[i]*factor/scale[i] for i in range(3))+(p[3],)
                              for p in item['points']]
                    temporary = c.curve(name=rig['namespace']+':artworkTemp', degree=item['degree'],
                                        pointWeight=points, knot=item['knots'], periodic=item['form']==3)
                    try:
                        if item['form'] == 2:
                            c.closeCurve(temporary, constructionHistory=False, replaceOriginal=True, preserveShape=True)
                        shape = c.listRelatives(temporary, shapes=True, fullPath=True)[0]
                        shape = c.parent(shape, node, shape=True, relative=True)[0]
                        shape = c.rename(shape, name)
                    finally:
                        c.delete(temporary)
                else:
                    shape = c.createNode('locator', name=name, parent=node, skipSelect=True)
                    c.setAttr(shape+'.localPosition', *[pivot[i]+item['position'][i]*factor/scale[i] for i in range(3)])
                    c.setAttr(shape+'.localScale', *[item['size'][i]*factor/abs(scale[i]) for i in range(3)])
                new_nodes.append(shape)
                if created is not None: created.append(shape)
                _set_display(shape, item['display'])
                c.setAttr(shape+'.visibility', item['visibility'])
                c.addAttr(shape, ln='controllerArtwork', at='bool', defaultValue=True)
                shapes.append(shape)
            report[role] = dict(template_role=source_role, scale=factor, shapes=shapes)
        rig['appearance'] = dict(version=VERSION, template=DATA.name, metrics=metrics, controls=report)
        rig.setdefault('nodes', []).extend(new_nodes)
        return rig['appearance']
    finally:
        c.autoKeyframe(state=old_auto)
        c.select(selection, r=True) if selection else c.select(clear=True)
