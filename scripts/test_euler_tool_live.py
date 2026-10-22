"""Disposable Maya regression for the standalone supplied Euler tool patch."""
import ast
import json
import runpy
import traceback
import uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

BASE = Path(__file__).resolve().parents[1]


def load_tool():
    path = BASE / '欧拉转换工具' / 'maya_speed_slider.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
             (n.name.startswith('_euler_') or n.name in
              ('switch_euler_order', 'calculate_euler_for_object', 'get_euler_keyframes', 'get_time_slider_range'))]
    import maya.mel as mel
    env = dict(cmds=c, mel=mel, ROTATE_ORDERS=['xyz', 'yzx', 'zxy', 'xzy', 'yxz', 'zyx'])
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(path), 'exec'), env)
    return env


def poses(nodes, times):
    result = {}
    undo=c.undoInfo(q=True,state=True)
    c.undoInfo(stateWithoutFlush=False)
    try:
        for t in times:
            c.currentTime(t)
            result[t] = {n:c.xform(n, q=True, ws=True, m=True) for n in nodes}
    finally:c.undoInfo(stateWithoutFlush=undo)
    return result


def error(expected):
    maximum = 0.0
    undo=c.undoInfo(q=True,state=True)
    c.undoInfo(stateWithoutFlush=False)
    try:
        for t, nodes in expected.items():
            c.currentTime(t)
            for n, matrix in nodes.items():
                maximum = max(maximum, max(abs(a-b) for a,b in zip(matrix,c.xform(n,q=True,ws=True,m=True))))
    finally:c.undoInfo(stateWithoutFlush=undo)
    return maximum


def run():
    from maya_agent.rigs.integrated import build
    suite = runpy.run_path(str(BASE/'scripts'/'test_integrated_rig_live.py'))
    curves = runpy.run_path(str(BASE/'scripts'/'test_external_constraints_live.py'))['_curves']
    api = load_tool()
    before = set(c.ls(uuid=True))
    original_curves = curves(c.ls(type='animCurve') or [])
    selection, frame = c.ls(sl=True, l=True) or [], c.currentTime(q=True)
    auto, modified = c.autoKeyframe(q=True,state=True), c.file(q=True,modified=True)
    rig, fixture, plain = None, None, None
    report = dict(cases=[], warnings=[])
    def output(message, kind, *_):
        if kind in (om.MCommandMessage.kWarning,om.MCommandMessage.kError) and len(report['warnings'])<20:
            report['warnings'].append(message)
    callback = om.MCommandMessage.addCommandOutputCallback(output)
    c.autoKeyframe(state=False)
    try:
        prefix = '_eulerVerify_'+uuid.uuid4().hex[:8]
        fixture, parts = suite['fixture'](prefix,True)
        parts = {k:v for k,v in parts.items() if k.startswith('arm')}
        originals = [n for p in parts.values() for n in p['targets']]
        for part in parts.values():
            part.update(live_alignment=True,space_wrist=True,space_upper_arm=True)
        c.currentTime(1)
        rig = build(parts,namespace=prefix,zero_controls=True)
        controls = [p['zero_controls'][role] for p in rig['parts'].values()
                    for role in ('shoulder_fk','middle_fk','end_fk')]
        watched = originals + [n for p in rig['parts'].values() for n in p['joints']]
        # Asymmetric large rotations, sparse fractional times, and authored pivots.
        for i, ctrl in enumerate(controls):
            c.currentTime(2.25)
            c.setKeyframe(ctrl,at='rotateY',t=2.25,v=c.getAttr(ctrl+'.rotateY')+12+i)
        times = sorted(set(c.keyframe(controls,q=True,tc=True)))
        for mode in (0,1):
            for p in rig['parts'].values():
                c.setAttr(p['zero_controls']['end_fk']+'.global', mode)
            expected = poses(watched,times)
            for order in api['ROTATE_ORDERS']:
                snapshot = curves(c.ls(type='animCurve') or [])
                zero_data = {n:c.getAttr(n+'.zeroChannelData') for n in controls}
                orders = {n:c.getAttr(n+'.rotateOrder') for n in controls}
                result = api['switch_euler_order'](controls, order)
                maximum = error(expected)
                assert maximum<1e-5, (mode,order,maximum)
                assert sorted(set(c.keyframe(controls,q=True,tc=True)))==times
                after = poses(watched,times)
                c.undo()
                restored=curves(snapshot)
                if restored!=snapshot:
                    report['undo_curve_diff']={n:{'before':value,'after':restored.get(n)}
                                               for n,value in snapshot.items() if restored.get(n)!=value}
                assert restored==snapshot, ('undo curves',mode,order)
                assert {n:c.getAttr(n+'.zeroChannelData') for n in controls}==zero_data
                assert {n:c.getAttr(n+'.rotateOrder') for n in controls}==orders
                assert error(expected)<1e-5
                c.redo()
                assert error(after)<1e-5
                c.undo()
                report['cases'].append(dict(mode=mode,order=order,error=maximum,undo_redo=True))
        # Forced post-write failure must restore exact originals and all offsets.
        snapshot = curves(c.ls(type='animCurve') or [])
        saved = {n:(c.getAttr(n+'.rotateOrder'),c.getAttr(n+'.zeroChannelData')) for n in controls}
        saved_nodes = set(c.ls(uuid=True))
        validator = api['_euler_validate']
        def fail(*_):raise RuntimeError('injected verification failure')
        api['_euler_validate']=fail
        try:
            api['switch_euler_order'](controls,'zyx')
            raise AssertionError('failure did not raise')
        except RuntimeError as exc:
            assert str(exc)=='injected verification failure'
        finally:api['_euler_validate']=validator
        assert curves(snapshot)==snapshot
        assert set(c.ls(uuid=True))==saved_nodes
        assert {n:(c.getAttr(n+'.rotateOrder'),c.getAttr(n+'.zeroChannelData')) for n in controls}==saved
        report['failure_rollback']=True
        # Analysis uses actual input, creates no duplicate nodes, and restores time.
        before_analysis=set(c.ls(uuid=True));t=c.currentTime(q=True)
        analysis=api['calculate_euler_for_object'](controls[0])
        assert set(c.ls(uuid=True))==before_analysis and c.currentTime(q=True)==t
        report['analysis']=analysis
        # Repeated conversions must read the updated zero metadata, not old offsets.
        for p in rig['parts'].values():c.setAttr(p['zero_controls']['end_fk']+'.global',0)
        expected=poses(watched,times)
        for order in ('xyz','zyx','yzx'):
            api['switch_euler_order'](controls,order)
            assert error(expected)<1e-5
        for _ in range(3):c.undo()
        assert error(expected)<1e-5
        report['repeated_conversion']=True
        # All-zero rotations retain the same bind orientation after conversion.
        c.undoInfo(openChunk=True,chunkName='EulerTestZeroPose')
        try:
            for ctrl in controls:
                for axis in 'XYZ':
                    plug=ctrl+'.rotate'+axis
                    incoming=c.connectionInfo(plug,sfd=True)
                    if incoming:c.disconnectAttr(incoming,plug)
                    c.setAttr(plug,0)
        finally:c.undoInfo(closeChunk=True)
        zero_pose=poses(watched,[c.currentTime(q=True)])
        api['switch_euler_order'](controls,'xyz')
        assert error(zero_pose)<1e-5
        for ctrl in controls:
            assert max(abs(v) for v in c.getAttr(ctrl+'.rotate')[0])<1e-8
        c.undo();c.undo()
        report['zero_pose']=True
        # Preflight rejects a locked axis without touching any other control.
        c.setAttr(controls[-1]+'.rotateZ',lock=True)
        snapshot=curves(c.ls(type='animCurve') or [])
        try:
            api['switch_euler_order'](controls,'zyx')
            raise AssertionError('locked channel was accepted')
        except ValueError:pass
        assert curves(snapshot)==snapshot
        c.setAttr(controls[-1]+'.rotateZ',lock=False)
        report['locked_rejection']=True
        # Ordinary animated joint, jointOrient and pivots must still work.
        plain=c.createNode('joint',name=prefix+'_ordinary',parent=fixture)
        c.setAttr(plain+'.jointOrient',11,17,-23)
        c.setAttr(plain+'.rotateAxis',4,-6,10)
        c.setAttr(plain+'.rotatePivot',.3,-.2,.4)
        c.setAttr(plain+'.rotateOrder',3)
        for t, v in ((1,(25,-18,40)),(2.5,(80,35,-24)),(7.25,(-45,23,105))):
            for axis,value in zip('XYZ',v):c.setKeyframe(plain,at='rotate'+axis,t=t,v=value)
        expected=poses([plain],[1,2.5,7.25])
        result=api['switch_euler_order']([plain],'xyz')
        assert error(expected)<1e-6
        report['ordinary_joint']=result
        c.undo()
        # Static conversion preserves pose and creates no animation curves.
        c.cutKey(plain,at=['rx','ry','rz'],clear=True)
        connected=c.listConnections(plain,s=True,d=False,type='animCurve') or []
        if connected:c.delete(connected)
        c.setAttr(plain+'.rotate',33,42,-70)
        expected=poses([plain],[c.currentTime(q=True)])
        result=api['switch_euler_order']([plain],'xyz')
        assert error(expected)<1e-6 and not c.keyframe(plain,q=True,tc=True)
        report['static']=result
        report['passed']=True
    except Exception:
        report['passed']=False
        report['traceback']=traceback.format_exc()
    finally:
        om.MMessage.removeCallback(callback)
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        for uid in set(c.ls(uuid=True))-before:
            nodes=c.ls(uid,l=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):
                c.delete(nodes[0])
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        report['original_nodes_preserved']=set(c.ls(uuid=True))==before
        report['original_curves_preserved']=curves(original_curves)==original_curves
        c.file(modified=modified)
        (BASE/'outputs'/'euler-tool-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
