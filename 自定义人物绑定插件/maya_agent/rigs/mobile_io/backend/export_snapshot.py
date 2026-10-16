"""Read-only exporter for the registered integrated rig. Run inside Maya.

This is a current-pose snapshot, not a portable Maya dependency-graph solver.
Never changes time, selection, channels, connections, scene name or save state.
"""
import hashlib
import json
from pathlib import Path

import maya.cmds as c
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma


def dag(node):
    s = om.MSelectionList()
    s.add(node)
    return s.getDagPath(0)


def uuid(node):
    return c.ls(node, uuid=True)[0]


def numbers(values):
    return [float(v) for v in values]


def point(p):
    return [float(p.x), float(p.y), float(p.z)]


def fingerprint():
    curves = {}
    for n in c.ls(type='animCurve') or []:
        curves[n] = [c.keyframe(n, q=True, tc=True), c.keyframe(n, q=True, vc=True)]
    transforms = {n: c.xform(n, q=True, ws=True, m=True)
                  for n in c.ls(type='transform', long=True) or []}
    joints = {n: c.xform(n, q=True, ws=True, m=True)
              for n in c.ls(type='joint', long=True) or []}
    return {'scene': c.file(q=True, sn=True), 'modified': c.file(q=True, modified=True),
            'frame': c.currentTime(q=True), 'selection': c.ls(sl=True, long=True) or [],
            'nodes': sorted(c.ls(long=True)), 'skins': sorted(c.ls(type='skinCluster')),
            'autoKey': c.autoKeyframe(q=True, state=True),
            'curvesHash': hashlib.sha256(json.dumps(curves, sort_keys=True).encode()).hexdigest(),
            'transformsHash': hashlib.sha256(json.dumps([transforms, joints], sort_keys=True).encode()).hexdigest()}


def export(root, path):
    root = c.ls(root, long=True)[0]
    before = fingerprint()
    metadata = json.loads(c.getAttr(root + '.integratedRigData'))
    controls, targets, warnings = [], [], []
    definitions=dict(metadata['parts'])
    if metadata.get('master_control'):
        definitions['character']={'controls':{'master':metadata['master_control']}}
    for item in metadata.get('generic_objects',[]):
        control=c.ls(item['control_uuid'],long=True)[0]
        target=c.ls(item['target_uuid'],long=True)[0]
        definitions['generic_'+str(item['number'])]={'controls':{'prop':control},'original_target_mapping':[{'target':target}]}
    for part, definition in definitions.items():
        mapping = dict(definition.get('controls', {}))
        mapping.update(definition.get('zero_controls', {}))
        for role, node in mapping.items():
            node = c.ls(node, long=True)[0]
            shapes = c.listRelatives(node, shapes=True, ni=True, fullPath=True) or []
            curves = []
            for shape in shapes:
                if c.nodeType(shape) != 'nurbsCurve' or not dag(shape).isVisible():
                    continue
                fn = om.MFnNurbsCurve(dag(shape))
                if fn.degree == 1:
                    points = [point(p) for p in fn.cvPositions(om.MSpace.kWorld)]
                else:
                    lo, hi = fn.knotDomain
                    points = [point(fn.getPointAtParam(lo + (hi-lo)*i/96, om.MSpace.kWorld)) for i in range(97)]
                if fn.form != om.MFnNurbsCurve.kOpen and points and points[0] != points[-1]:
                    points.append(points[0])
                curves.append(points)
            channels = {}
            for attr in c.listAttr(node, keyable=True) or []:
                plug = node + '.' + attr
                try:
                    value = c.getAttr(plug)
                    if isinstance(value, (int, float, bool)):
                        channels[attr] = {'value': value, 'locked': c.getAttr(plug, lock=True),
                                          'keyTimes': c.keyframe(plug, q=True, tc=True) or [],
                                          'keyValues': c.keyframe(plug, q=True, vc=True) or []}
                except RuntimeError:
                    pass
            controls.append({'id': uuid(node), 'role': role, 'part': part, 'path': node,
                             'name': node.split('|')[-1], 'position': numbers(c.xform(node,q=True,ws=True,t=True)),
                             'worldMatrix': numbers(c.xform(node,q=True,ws=True,m=True)),
                             'rotateOrder': c.getAttr(node+'.rotateOrder'),
                             'channels': channels, 'curves': curves, 'visible': bool(curves)})
        for item in definition.get('original_target_mapping', []):
            targets.append(item)

    # Collect skin clusters from the registered original targets, never unrelated characters.
    target_nodes = []
    def find_targets(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ('target', 'original_target') and isinstance(v,str) and c.objExists(v):
                    target_nodes.append(v)
                else:
                    find_targets(v)
        elif isinstance(value,list):
            for v in value:
                find_targets(v)
    find_targets(targets)
    if not target_nodes:
        raise RuntimeError('No registered original targets; refusing to export unrelated meshes.')
    skins = set()
    for target in target_nodes:
        skins.update(c.listConnections(target, type='skinCluster') or [])
    if not skins:
        raise RuntimeError('No skin cluster connected to the registered targets.')
    meshes, joint_nodes = [], set()
    for skin in sorted(skins):
        sel = om.MSelectionList(); sel.add(skin)
        skinfn = oma.MFnSkinCluster(sel.getDependNode(0))
        influences = skinfn.influenceObjects()
        for influence in influences:
            n = influence.fullPathName()
            while n and c.nodeType(n) == 'joint':
                joint_nodes.add(n)
                parents = c.listRelatives(n, parent=True, fullPath=True) or []
                n = parents[0] if parents else ''
        for geometry in c.skinCluster(skin, q=True, geometry=True) or []:
            dp = dag(geometry)
            if dp.apiType() == om.MFn.kTransform:
                dp.extendToShape()
            mesh = om.MFnMesh(dp)
            points = [point(p) for p in mesh.getPoints(om.MSpace.kWorld)]
            counts, indices = mesh.getTriangles()
            component = om.MFnSingleIndexedComponent()
            vertex_component = component.create(om.MFn.kMeshVertComponent)
            component.setCompleteData(mesh.numVertices)
            weights, influence_count = skinfn.getWeights(dp, vertex_component)
            sparse = []
            for vertex in range(mesh.numVertices):
                row = []
                for i in range(influence_count):
                    weight = weights[vertex*influence_count+i]
                    if weight != 0:
                        row.extend([i, float(weight)])
                sparse.append(row)
            meshes.append({'id': uuid(dp.fullPathName()), 'name': dp.fullPathName(),
                           'positions': points, 'triangles': list(indices),
                           'skin': {'id':uuid(skin), 'name':skin,
                                    'method':c.getAttr(skin+'.skinningMethod'),
                                    'influences':[{'id':uuid(i.fullPathName()), 'path':i.fullPathName(),
                                        'bindPreMatrix':numbers(c.getAttr(skin+'.bindPreMatrix[%d]' % skinfn.indexForInfluenceObject(i)))} for i in influences],
                                    'weights':sparse},
                           'vertexSpace':'evaluated_world_at_snapshot_frame'})
    joints = []
    for n in sorted(joint_nodes):
        parents = c.listRelatives(n, parent=True, fullPath=True) or []
        parent = parents[0] if parents and parents[0] in joint_nodes else None
        joints.append({'id':uuid(n), 'name':n.split('|')[-1], 'path':n,
                       'parentId':uuid(parent) if parent else None,
                       'position':numbers(c.xform(n,q=True,ws=True,t=True)),
                       'worldMatrix':numbers(c.xform(n,q=True,ws=True,m=True))})
    package = {'format':'maya-rig-snapshot', 'schemaVersion':2,
               'characterId':uuid(root), 'name':metadata['namespace'], 'rigVersion':metadata['version'],
               'sourceScene':before['scene'], 'sourceFrame':before['frame'],
               'unit':c.currentUnit(q=True, linear=True), 'upAxis':c.upAxis(q=True, axis=True),
               'timeUnit':c.currentUnit(q=True, time=True),
               'frameRange':[c.playbackOptions(q=True,min=True),c.playbackOptions(q=True,max=True)],
               'capabilities':{'snapshot3d':True,'offlineRigSolver':False,'animationRoundTrip':False},
               'controls':controls,'joints':joints,'meshes':meshes,'rigMetadata':metadata,'warnings':warnings}
    import runpy
    runpy.run_path(str(Path(__file__).with_name('export_modes.py')))['extend_snapshot'](package)
    after = fingerprint()
    if after != before:
        raise RuntimeError('Scene state changed during read-only export; file not written.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(str(path))
    raw = json.dumps(package,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    path.write_bytes(raw)
    summary = {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
               'characterId':package['characterId'],'rigVersion':package['rigVersion'],
               'controls':len(controls),'visibleControls':sum(x['visible'] for x in controls),
               'joints':len(joints),'meshes':len(meshes),
               'vertices':sum(len(m['positions']) for m in meshes),
               'triangles':sum(len(m['triangles'])//3 for m in meshes),
               'parts':list(metadata['parts']), 'sourceFrame':before['frame'],
               'sceneUnchanged':after==before, 'sceneFingerprint':before}
    path.with_suffix('.report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return {k:v for k,v in summary.items() if k!='sceneFingerprint'}
