"""Verify integrated body artwork in a disposable standalone Maya scene."""
import json
import math
import sys
from pathlib import Path


def verify():
    import maya.cmds as cmds
    import maya.api.OpenMaya as om
    from maya_agent.rigs.integrated import build

    reports = []
    for count in (2, 4, 8):
        targets = []
        for index in range(count):
            target = cmds.createNode('joint', name='cubeTarget{}_{}'.format(count, index))
            cmds.setAttr(target + '.translate', 0, index * 10, 0)
            cmds.setAttr(target + '.jointOrient', index * 13, index * -21, 90)
            targets.append(target)
        before = {target: cmds.xform(target, q=True, ws=True, matrix=True) for target in targets}
        rig = build({'body': {'targets': targets}}, namespace='cubeCheck{}'.format(count))
        body = rig['parts']['body']
        for role, artwork in body['appearance']['controls'].items():
            control = body['controls'][role]
            pivot = cmds.xform(control, q=True, os=True, rp=True)
            for shape in artwork['shapes']:
                selection = om.MSelectionList()
                selection.add(shape)
                curve = om.MFnNurbsCurve(selection.getDagPath(0))
                points = [tuple(point[axis] - pivot[axis] for axis in range(3)) for point in curve.cvPositions()]
                half = max(abs(value) for point in points for value in point)
                assert curve.degree == 1
                assert len({tuple(round(value, 6) for value in point) for point in points}) == 8
                assert all(abs(abs(value) - half) < 1e-5 for point in points for value in point), role
                edges = set()
                for start, end in zip(points, points[1:]):
                    assert sum(abs(first - second) > 1e-5 for first, second in zip(start, end)) == 1
                    assert math.isclose(math.dist(start, end), half * 2, abs_tol=1e-5)
                    edges.add(tuple(sorted((start, end))))
                assert len(edges) == 12, (role, len(edges))
        error = max(abs(first - second) for target in targets
                    for first, second in zip(before[target], cmds.xform(target, q=True, ws=True, matrix=True)))
        assert error < 1e-5, error
        reports.append(dict(segments=count, controls=len(body['controls']), pose_error=error))
    return reports


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import maya.standalone
    maya.standalone.initialize(name='python')
    try:
        print(json.dumps(verify(), indent=2))
    finally:
        maya.standalone.uninitialize()
