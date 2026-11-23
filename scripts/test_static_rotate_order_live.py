"""Disposable live fixtures; never open or save a user scene."""
import json
from pathlib import Path
from unittest.mock import patch
import maya.cmds as c


def run(destination):
    from maya_agent.rigs.custom_body.targets import _static_rotate_order
    from maya_agent.rigs.integrated import builder
    from maya_agent.rigs.mobile_io import service
    fingerprint = service.module('export_snapshot')['fingerprint']
    before = fingerprint()
    selection = c.ls(sl=True, long=True) or []
    frame = c.currentTime(q=True)
    auto = c.autoKeyframe(q=True, state=True)
    ns = 'staticOrderRegression'
    if c.namespace(exists=ns):
        raise RuntimeError('Test namespace already exists')
    results = []
    initial = set(c.ls(long=True))
    try:
        c.autoKeyframe(state=False)
        c.namespace(add=ns)
        setting = c.createNode('transform', name=ns + ':settings')
        c.addAttr(setting, ln='order', at='enum', en='xyz:yzx:zxy:xzy:yxz:zyx')
        relay = c.createNode('transform', name=ns + ':relay')
        target = c.createNode('transform', name=ns + ':target')
        c.connectAttr(setting + '.order', relay + '.rotateOrder')
        c.connectAttr(relay + '.rotateOrder', target + '.rotateOrder')
        c.setAttr(target + '.ty', 10)
        for t, v in ((1, 15), (3, -25), (5, 70)):
            for attr, factor in (('rx', 1), ('ry', .6), ('rz', -.3)):
                c.setKeyframe(target, at=attr, t=t, v=v * factor)
        config = {'head': dict(targets=[target], compatible_inputs=True,
                               start_frame=1, end_frame=5)}
        for order in range(6):
            c.setAttr(setting + '.order', order)
            assert _static_rotate_order(target + '.rotateOrder')
            expected = {}
            for t in range(1, 6):
                c.currentTime(t)
                expected[t] = c.xform(target, q=True, ws=True, m=True)
            c.currentTime(1)
            edges = {a: c.connectionInfo(target + '.' + a, sfd=True)
                     for a in ('rx', 'ry', 'rz')}
            base = set(c.ls(long=True))
            # Inject a failure after incoming TR has been detached.
            original = c.parentConstraint
            def fail(*args, **kwargs):
                if kwargs.get('name', '').startswith(ns + 'Build:head_target'):
                    raise RuntimeError('static order injected failure')
                return original(*args, **kwargs)
            try:
                with patch.object(c, 'parentConstraint', fail):
                    builder.build(config, namespace=ns + 'Build', create_master=False)
            except RuntimeError as exc:
                assert str(exc) == 'static order injected failure', str(exc)
            else:
                raise AssertionError('Failure injection missed')
            assert set(c.ls(long=True)) == base
            assert all(c.connectionInfo(target + '.' + a, sfd=True) == s for a, s in edges.items())
            rig = builder.build(config, namespace=ns + 'Build', create_master=False)
            error = 0.
            for t in range(1, 6):
                c.currentTime(t)
                c.dgdirty(allPlugs=True)
                actual = c.xform(target, q=True, ws=True, m=True)
                error = max(error, max(abs(a-b) for a, b in zip(actual, expected[t])))
            assert error < 1e-4, error
            assert c.isConnected(relay + '.rotateOrder', target + '.rotateOrder')
            assert c.isConnected(setting + '.order', relay + '.rotateOrder')
            # Only generated fixture nodes; keep and reconnect original fixture curves.
            added = list(set(c.ls(long=True)) - base)
            constraints = [n for n in added if c.objExists(n) and c.objectType(n, isAType='constraint')]
            if constraints:
                c.delete(constraints)
            for attr, source in edges.items():
                curve = source.split('.')[0]
                for dst in c.listConnections(curve + '.message', s=False, d=True, p=True) or []:
                    if dst.startswith(ns + 'Build:'):
                        c.disconnectAttr(curve + '.message', dst)
                if not c.isConnected(source, target + '.' + attr):
                    c.connectAttr(source, target + '.' + attr)
            remaining = [n for n in added if c.objExists(n)]
            if remaining:
                c.delete(remaining)
            for namespace in sorted(c.namespaceInfo(listOnlyNamespaces=True, recurse=True) or [], key=len, reverse=True):
                if namespace.startswith(ns + 'Build'):
                    c.namespace(removeNamespace=namespace)
            results.append(dict(order=order, maxWorldError=error, rollback=True))
        # A flat animation curve is still animated and must remain rejected.
        c.setKeyframe(setting, at='order', t=1, v=0)
        c.setKeyframe(setting, at='order', t=5, v=0)
        assert not _static_rotate_order(target + '.rotateOrder')
        try:
            builder.preflight(config)
        except ValueError as exc:
            assert 'rotateOrder' in str(exc)
        else:
            raise AssertionError('Animated order passed preflight')
        c.cutKey(setting, at='order', clear=True)
        src = c.connectionInfo(setting + '.order', sfd=True)
        if src:
            c.disconnectAttr(src, setting + '.order')
        computed = c.createNode('addDoubleLinear', name=ns + ':computed')
        c.connectAttr(computed + '.output', setting + '.order')
        assert not _static_rotate_order(target + '.rotateOrder')
        results.append(dict(animatedRejected=True, computedRejected=True))
    finally:
        added = list(set(c.ls(long=True)) - initial)
        if added:
            c.delete(added)
        for namespace in sorted(c.namespaceInfo(listOnlyNamespaces=True, recurse=True) or [], key=len, reverse=True):
            if namespace.startswith(ns):
                c.namespace(removeNamespace=namespace)
        c.currentTime(frame)
        c.select(selection, r=True) if selection else c.select(clear=True)
        c.autoKeyframe(state=auto)
        c.dgdirty(allPlugs=True)
        c.refresh(force=True)
        c.file(modified=before['modified'])
    after = fingerprint()
    report = dict(passed=True, cases=results, sceneUnchanged=before == after,
                  differences=[k for k in before if before[k] != after[k]])
    Path(destination).write_text(json.dumps(report, indent=2), 'utf8')
    assert before == after, report
    return report
