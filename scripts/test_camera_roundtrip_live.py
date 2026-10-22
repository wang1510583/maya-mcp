"""Isolated sparse camera roundtrip through actual Java editor serialization."""
import copy
import hashlib
import json
import runpy
import subprocess
import uuid
from pathlib import Path
import maya.cmds as c

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / '自定义人物绑定插件/maya_agent/rigs/mobile_io/backend'


def run(output, java, classpath, orthographic=False):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    curve = runpy.run_path(str(BACKEND / 'animation_curves.py'))
    importer = runpy.run_path(str(BACKEND / 'mobile_animation_io.py'))['apply']
    fp = runpy.run_path(str(BACKEND / 'export_snapshot.py'))['fingerprint']
    before = fp()
    namespace = c.namespaceInfo(currentNamespace=True)
    ns = 'cameraRoundtrip_' + uuid.uuid4().hex[:10]
    report = {}
    from maya_agent.rigs import arm_ik
    busy = arm_ik._busy
    arm_ik._busy = True
    try:
        c.autoKeyframe(state=False)
        c.namespace(add=ns)
        c.namespace(set=ns)
        root = c.createNode('transform', name='rig')
        ctrl = c.createNode('transform', name='control', parent=root)
        parent = c.createNode('transform', name='cameraParent')
        c.setAttr(parent + '.ry', 27)
        c.setAttr(parent + '.tx', 3)
        cam, shape = c.camera(name='shot')
        c.setAttr(shape + '.orthographic', orthographic)
        c.parent(cam, parent)
        root, ctrl, cam, shape = [c.ls(n, long=True)[0] for n in (root, ctrl, cam, shape)]
        c.setAttr(cam + '.rotateOrder', 2)
        c.setAttr(cam + '.tz', 20)
        for attr, times in [('tx', [0, 4.5, 20]), ('ry', [1, 8, 19])]:
            for i, t in enumerate(times):
                c.setKeyframe(cam, at=attr, t=t, v=i * 4, itt='spline', ott='spline')
        for t, value in [(2, 30), (13, 55), (22, 45)]:
            c.setKeyframe(shape, at='focalLength', t=t, v=value, itt='linear', ott='linear')
        c.keyTangent(cam + '.tx', e=True, weightedTangents=True, lock=False, weightLock=False)
        c.keyTangent(cam + '.tx', e=True, ia=23, oa=-12, iw=1.6, ow=2.3)
        c.setInfinity(cam + '.tx', pri='cycle', poi='oscillate')
        c.keyframe(cam + '.tx', e=True, t=(4.5, 4.5), breakdown=True)
        for t in [0, 20]:
            c.setKeyframe(ctrl, at='tx', t=t, v=t * .2)
        meta = dict(version='camera-roundtrip', parts={'test': {'controls': {'main': ctrl}}})
        c.addAttr(root, ln='integratedRigData', dt='string')
        c.setAttr(root + '.integratedRigData', json.dumps(meta), type='string')
        attrs = curve['ATTRS']
        uid, cid = [c.ls(n, uuid=True)[0] for n in (ctrl, root)]
        # Deliberately old project: no keyFrames/sourceCurves/lens in camera snapshot.
        camera = runpy.run_path(str(BACKEND / 'export_cameras.py'))['capture']([shape], 0, 20)[0]
        legacy = copy.deepcopy(camera)
        legacy.pop('keyFrames')
        legacy.pop('sourceCurves')
        for s in legacy['samples']:
            s.pop('lens')
        snap = dict(characterId=cid, rigVersion=meta['version'], sourceFrame=before['frame'],
                    frameRange=[0, 20], joints=[], meshes=[], cameras=[legacy],
                    controls=[dict(id=uid, part='test', role='main',
                                   channels={a: dict(value=0, locked=False) for a in attrs})])
        raw = json.dumps(snap).encode()
        (out / 'snapshot.json').write_bytes(raw)
        graph = dict(sourceSnapshotSha256=hashlib.sha256(raw).hexdigest(),
                     ops=[dict(op='input', name=ctrl + '.' + a,
                               data=dict(id=uid, axis=i, base=0)) for i, a in enumerate(attrs)])
        (out / 'graph.json').write_text(json.dumps(graph), 'utf8')
        runpy.run_path(str(BACKEND / 'export_animation.py'))['export'](
            str(out / 'snapshot.json'), str(out / 'graph.json'),
            str(out / 'original.json'), str(out / 'reference.json'))
        completed = subprocess.run([java, '-cp', classpath, 'com.example.customrigtest.CameraRoundtripTest', str(out)],
                                   capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report['java'] = completed.stdout.strip()
        package = json.loads((out / 'android-unchanged.json').read_text('utf8'))
        expected = {n + '.' + a: curve['capture'](n + '.' + a)
                    for n, names in [(cam, ('translateX', 'rotateY', 'translateZ')), (shape, ('focalLength',))]
                    for a in names}
        query = [i / 8 for i in range(-8, 185)]
        poses = {p: [c.getAttr(p, time=t) for t in query] for p in expected}
        for p in expected:
            for t in range(21):
                c.setKeyframe(p, t=t, v=99)
        def apply(name, dry=False):
            return importer(str(out / name), snapshot_path=str(out / 'snapshot.json'),
                            backup_directory=str(out / 'backups'), dry_run=dry)
        report['unchangedImport'] = apply('android-unchanged.json')
        for p, want in expected.items():
            got = curve['capture'](p)
            for field in ('times', 'values', 'inTangentType', 'outTangentType', 'weightedTangents', 'breakdownTimes', 'preInfinity', 'postInfinity'):
                assert got.get(field) == want.get(field), (p, field)
        error = max(abs(c.getAttr(p, time=t) - v) for p in expected for t, v in zip(query, poses[p]))
        assert error < 1e-7, error
        report['unchangedCurveMaxError'] = error
        # FPS conversion retains sparse fractional times and fixed weighted handle shape.
        converted = copy.deepcopy(package)
        converted['fps'] *= 2
        (out / 'converted.json').write_text(json.dumps(converted), 'utf8')
        apply('converted.json')
        error = max(abs(c.getAttr(p, time=t * .5) - v) for p in expected for t, v in zip(query, poses[p]))
        assert error < 1e-7, error
        report['fpsConversionMaxError'] = error
        report['editedImport'] = apply('android-edited.json')
        for attr in ('tx', 'ty', 'tz', 'rx', 'ry', 'rz'):
            assert c.keyframe(cam + '.' + attr, q=True, tc=True) == [2., 12.]
        edited = json.loads((out / 'android-edited.json').read_text('utf8'))
        values = edited['cameraTracks'][camera['id']]['samples']
        error = 0
        for item in values:
            if item['frame'] not in [2, 12]:
                continue
            c.currentTime(item['frame'])
            world = c.xform(cam, q=True, ws=True, m=True)
            error = max(error, max(abs(a-b) for a,b in zip(world,item['state']['world'])))
            if orthographic:
                assert abs(c.getAttr(shape+'.orthographicWidth') - item['state']['lens']['orthographicWidth']) < 1e-7
        assert error < 1e-7, error
        report['editedKeyMatrixMaxError'] = error
        report['orthographic'] = orthographic
        assert c.keyframe(shape + '.focalLength', q=True, tc=True) == [2., 12.]
        runpy.run_path(str(BACKEND / 'export_animation.py'))['export'](
            str(out / 'snapshot.json'), str(out / 'graph.json'),
            str(out / 'reexport.json'), str(out / 'reexport-reference.json'))
        reexport = json.loads((out / 'reexport.json').read_text('utf8'))
        assert reexport['cameras'][0]['keyFrames'] == [2., 12.]
        report['reexportKeyFrames'] = reexport['cameras'][0]['keyFrames']
        report['emptyImport'] = apply('android-empty.json')
        assert not c.keyframe(cam, q=True, tc=True)
        assert not c.keyframe(shape, q=True, tc=True)
        # Guard before edits, plus actual failure rollback of the shared transaction.
        bad = copy.deepcopy(edited)
        bad['cameras'][0]['id'] = 'not-a-project-camera'
        (out / 'bad-camera.json').write_text(json.dumps(bad), 'utf8')
        stable = fp()
        try:
            apply('bad-camera.json')
            raise AssertionError('Foreign camera accepted')
        except ValueError:
            pass
        assert stable == fp()
        for t, v in [(0, 0), (10, 2)]:
            c.setKeyframe(parent, at='ty', t=t, v=v)
        stable = fp()
        try:
            apply('android-edited.json')
            raise AssertionError('Animated parent accepted')
        except ValueError:
            pass
        assert stable == fp()
        c.cutKey(parent, at='ty', clear=True)
        c.setAttr(parent + '.ty', 0)
        c.setAttr(cam + '.tx', lock=True)
        stable = fp()
        try:
            apply('android-edited.json')
            raise AssertionError('Locked camera accepted')
        except ValueError:
            pass
        assert stable == fp()
        c.setAttr(cam + '.tx', lock=False)
        stable = fp()
        real_set_key = c.setKeyframe
        calls = [0]
        def fail(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 4:
                raise RuntimeError('Injected camera write failure')
            return real_set_key(*args, **kwargs)
        c.setKeyframe = fail
        try:
            try:
                apply('android-edited.json')
                raise AssertionError('Failure injection did not run')
            except RuntimeError as exc:
                assert 'Injected' in str(exc), str(exc)
        finally:
            c.setKeyframe = real_set_key
        assert stable == fp(), 'Rollback changed scene'
        report['guardsAndRollback'] = 'PASS'
    finally:
        c.namespace(set=namespace)
        if c.namespace(exists=ns):
            c.namespace(removeNamespace=ns, deleteNamespaceContent=True)
        c.currentTime(before['frame'])
        c.dgdirty(allPlugs=True)
        c.refresh(force=True)
        c.select(before['selection'], r=True) if before['selection'] else c.select(clear=True)
        c.autoKeyframe(state=before['autoKey'])
        c.file(modified=before['modified'])
        arm_ik._busy = busy
        arm_ik._sync_mode_cache()
        report['sceneRestored'] = before == fp()
        (out / 'report.json').write_text(json.dumps(report, indent=2), 'utf8')
    assert report['sceneRestored'], report
    return report
