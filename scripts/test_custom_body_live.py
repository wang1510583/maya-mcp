"""Test the modular tool via the actual Maya registry; leave all user nodes untouched."""
import json
from pathlib import Path
import math
import uuid
import maya.cmds as cmds
import maya.api.OpenMaya as om
from maya_agent.rigs.custom_body import builder, drivers
from maya_agent.rigs.custom_body.definition import VERSION, load_definition
from maya_agent.tools.registry import run_tool

root = Path(__file__).resolve().parents[1]
data = load_definition()
original_nodes = set(cmds.ls(long=True) or [])
original_selection = cmds.ls(selection=True, long=True) or []
original_namespace = cmds.namespaceInfo(currentNamespace=True)
original_frame = cmds.currentTime(query=True)
original_dirty = cmds.file(query=True, modified=True)
original_matrices = {n:cmds.xform(n, query=True, worldSpace=True, matrix=True)
                     for n in cmds.ls(type='transform', long=True) + cmds.ls(type='joint', long=True)}
original_layers = {n:cmds.getAttr(n+'.visibility') for n in cmds.ls(type='displayLayer')}
base = '_CBR_QA_' + uuid.uuid4().hex[:8]
made = []
checks = []

def invoke(**args):
    response = run_tool('create_custom_body_rig', args)
    if not response.ok:
        raise AssertionError(response.error)
    made.append(response.data)
    return response.data

def near(a, b):
    return abs(a-b) < 1e-5

try:
    a = invoke(namespace=base)
    assert a['node_count'] == 42 and a['connection_count'] == 113
    assert cmds.getAttr(base + ':hips_zero.customBodyRigVersion') == VERSION
    for row in data['nodes']:
        node = row['name'].replace('testSetup:', base+':')
        assert cmds.nodeType(node) == row['type']
        if 'curve' in row:
            selection = om.MSelectionList(); selection.add(node)
            curve = om.MFnNurbsCurve(selection.getDagPath(0))
            assert curve.numCVs == len(row['curve']['cvs'])
            assert all(near(a,b) for p,q in zip(curve.cvPositions(), row['curve']['cvs']) for a,b in zip((p.x,p.y,p.z,p.w),q))
    for edge in data['connections']:
        if edge['source'].startswith('layerManager.'):
            continue
        assert cmds.isConnected(edge['source'].replace('testSetup:',base+':'), edge['destination'].replace('testSetup:',base+':'))
    for i,j in enumerate(a['joints']):
        assert all(near(x,y) for x,y in zip(cmds.xform(j,query=True,worldSpace=True,translation=True), [0,2*i,0]))
    checks.append('registry build, version tag, 42 nodes, connections and original curve shapes')

    chest = a['controls']['chest']
    cmds.setAttr(chest+'.translate',3,1.5,-1.2,type='double3')
    factors=[0,cmds.getAttr(base+':multiplyDivide2.input2X'),cmds.getAttr(base+':multiplyDivide1.input2X'),1]
    for i,(j,f) in enumerate(zip(a['joints'],factors)):
        assert all(near(x,y) for x,y in zip(cmds.xform(j,query=True,worldSpace=True,translation=True),[3*f,2*i+1.5*f,-1.2*f]))
    cmds.setAttr(chest+'.translate',0,0,0,type='double3')
    cmds.setAttr(chest+'.rotateZ',30)
    for index,moving in [('Lower',1),('Upper',2)]:
        half=math.radians(15)
        expected=math.degrees(2*math.atan2(moving*math.sin(half),moving*math.cos(half)+(3-moving)))
        assert near(cmds.getAttr(base+':spine'+index+'_connect.rotateZ'),expected)
    cmds.setAttr(chest+'.rotateZ',0)
    checks.append('chest translation distribution and quaternion rotation blending')

    b=invoke(namespace=base)
    assert b['namespace']==base+'_02'
    assert {e['source'] for e in a['display_layer_connections']}.isdisjoint({e['source'] for e in b['display_layer_connections']})
    assert set(cmds.ls(type='displayLayer')) == set(original_layers)
    cmds.setAttr(a['controls']['hips']+'.overrideColor',6)
    assert cmds.getAttr(b['controls']['hips']+'.overrideColor') == 14
    assert all(cmds.getAttr(n+'.visibility')==v for n,v in original_layers.items())
    cmds.setAttr(a['controls']['hips']+'.translateX',4)
    assert near(cmds.xform(b['joints'][0],query=True,worldSpace=True,translation=True)[0],0)
    checks.append('repeat creation isolates display overrides without extra layers')

    before=set(cmds.ls(long=True) or [])
    denied=run_tool('create_custom_body_rig',{'namespace':base,'on_conflict':'error'})
    assert not denied.ok and set(cmds.ls(long=True) or [])==before
    invalid=run_tool('create_custom_body_rig',{'namespace':'bad:name'})
    assert not invalid.ok and set(cmds.ls(long=True) or [])==before
    checks.append('collision and invalid names fail before modifying nodes')

    original_connect=drivers.connect
    def fail_after_creation(ctx):
        raise RuntimeError('intentional rollback probe')
    drivers.connect=fail_after_creation
    try:
        failed=run_tool('create_custom_body_rig',{'namespace':base+'_failure'})
        assert not failed.ok and 'intentional rollback probe' in failed.error
    finally:
        drivers.connect=original_connect
    assert set(cmds.ls(long=True) or [])==before
    assert not cmds.namespace(exists=base+'_failure')
    checks.append('failed build removes only its own nodes and namespace')

finally:
    for rig in reversed(made):
        assert rig['namespace'].startswith(base)
        for n in reversed(rig['nodes']):
            if cmds.objExists(n): cmds.delete(n)
        if cmds.namespace(exists=rig['namespace']): cmds.namespace(removeNamespace=rig['namespace'])
    cmds.namespace(setNamespace=original_namespace)
    cmds.select(original_selection,replace=True) if original_selection else cmds.select(clear=True)

assert set(cmds.ls(long=True) or [])==original_nodes, {'added': sorted(set(cmds.ls(long=True) or [])-original_nodes), 'missing':sorted(original_nodes-set(cmds.ls(long=True) or []))}
assert cmds.currentTime(query=True)==original_frame
assert all(all(near(a,b) for a,b in zip(matrix,cmds.xform(n,query=True,worldSpace=True,matrix=True))) for n,matrix in original_matrices.items())
assert all(cmds.getAttr(n+'.visibility')==v for n,v in original_layers.items())
cmds.file(modified=original_dirty)
result={'tool':'自定义身体绑定','version':VERSION,'checks':checks,'user_nodes_and_pose_preserved':True,'temporary_rigs_removed':True}
output=root/'outputs/custom-body-tests'; output.mkdir(parents=True,exist_ok=True)
(output/'live-tests.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
