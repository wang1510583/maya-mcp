"""Read-only export checks using disposable cameras; preserve the open scene."""
import json
import runpy
from pathlib import Path
import maya.cmds as c

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / '自定义人物绑定插件/maya_agent/rigs/mobile_io/backend'


def run():
    export = runpy.run_path(str(BACKEND / 'export_cameras.py'))
    fingerprint = runpy.run_path(str(BACKEND / 'export_snapshot.py'))['fingerprint']
    before = fingerprint()
    selected = c.ls(sl=True, long=True)
    frame = c.currentTime(q=True)
    modified = c.file(q=True, modified=True)
    namespace = c.namespaceInfo(currentNamespace=True)
    undo = c.undoInfo(q=True, state=True)
    test_namespace = 'mobileCameraKeysTest'
    if c.namespace(exists=test_namespace):
        raise RuntimeError('Test namespace already exists')
    c.undoInfo(stateWithoutFlush=False)
    try:
        c.namespace(add=test_namespace)
        c.namespace(set=test_namespace)
        parent = c.createNode('transform', name='camera_parent')
        camera, shape = c.camera(name='animated')
        c.parent(camera, parent)
        for t, value in [(0, 0), (8, 5)]:
            c.setKeyframe(parent, at='tx', time=t, value=value)
        for t, value in [(2, 0), (5, 25)]:
            c.setKeyframe(camera, at='ry', time=t, value=value)
        for t, value in [(1, 35), (6.5, 50)]:
            c.setKeyframe(shape, at='focalLength', time=t, value=value)
        static, static_shape = c.camera(name='constant_keys')
        for t in [0, 4, 8]:
            c.setKeyframe(static, at='tx', time=t, value=2)
        c.currentTime(3)
        c.select([camera, static])
        fixture_before = fingerprint()
        rows = export['capture']([shape, static_shape], 0, 8)
        assert rows[0]['keyFrames'] == [0., 1., 2., 5., 6.5, 8.]
        assert rows[1]['keyFrames'] == [0., 4., 8.]
        assert len(rows[1]['samples']) == 1, 'Static dedup must retain authored markers'
        assert fixture_before == fingerprint(), 'Export changed fixture state'
    finally:
        c.namespace(set=namespace)
        c.namespace(removeNamespace=test_namespace, deleteNamespaceContent=True)
        c.currentTime(frame)
        c.select(selected, replace=True) if selected else c.select(clear=True)
        c.dgdirty(allPlugs=True)
        c.refresh(force=True)
        c.file(modified=modified)
        c.undoInfo(stateWithoutFlush=undo)
    assert before == fingerprint(), 'Export test changed user scene'
    print(json.dumps({'pass': True, 'checks': ['ancestor keys', 'transform keys',
          'lens keys', 'fractional markers', 'static dedup', 'scene restored']}))


if __name__ == '__main__':
    run()
