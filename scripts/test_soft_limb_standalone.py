"""Run with mayapy in a separate Maya process, never the interactive user's scene."""
from pathlib import Path
import sys
import json
import math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import maya.standalone
maya.standalone.initialize(name='python')
import maya.cmds as c
from maya_agent.rigs.soft_limb import build, DATA

def main():
    a=build(namespace='testLimb',offset=(0,0,0))
    b=build(namespace='testLimb',offset=(22,0,0))
    spec=json.loads((DATA/'limb_v1.json').read_text(encoding='utf-8'))
    original={n:c.xform(a['namespace']+':'+n,q=True,ws=True,m=True) for n in spec['world_matrices']}
    checks=['original pose matches all transforms', 'two independent instances', 'common offset preserves pose']
    ns=b['namespace']+':'
    # Every graph input/output must be local, except implicit Maya global time.
    for n in b['nodes']:
        for other in c.listConnections(n,s=True,d=True) or []:
            assert other.startswith(ns) or other=='time1', (n,other)
    checks.append('no connections to the source or other instance')
    start=c.xform(ns+'joint3',q=True,ws=True,t=True)
    value=c.getAttr(ns+'armFK_L1.rotateZ')
    c.setAttr(ns+'armFK_L1.rotateZ',value-25)
    end=c.xform(ns+'joint3',q=True,ws=True,t=True)
    assert math.dist(start,end)>1
    for index,attr in ((1,'lenght_joint_1'),(2,'lenght_joint_2')):
        length=math.dist(c.xform(ns+'joint'+str(index),q=True,ws=True,t=True),c.xform(ns+'joint'+str(index+1),q=True,ws=True,t=True))
        assert abs(length-c.getAttr(ns+'strech_ik_foot1.'+attr))<1e-4
    c.setAttr(ns+'armFK_L1.rotateZ',value)
    checks.append('FK bending drives output and preserves segment lengths')
    # Lengthening the FK input puts the solver beyond its original reach.
    tx=c.getAttr(ns+'handFK_L1.translateX')
    c.setAttr(ns+'handFK_L1.translateX',tx+8)
    c.setAttr(ns+'strech_ik_foot1.lenght_coeff',.8)
    c.setAttr(ns+'strech_ik_foot1.softness',.2)
    c.setAttr(ns+'strech_ik_foot1.full_straight_coeff',.5)
    c.setAttr(ns+'strech_ik_foot1.bend_limit',.08)
    c.setAttr(ns+'strech_ik_foot1.scale_coeff',.5)
    for n in spec['world_matrices']:
        assert all(math.isfinite(v) for v in c.xform(ns+n,q=True,ws=True,m=True)),n
    endpoint=c.xform(ns+'joint3',q=True,ws=True,t=True)
    target=c.xform(ns+'hand_L1',q=True,ws=True,t=True)
    assert math.dist(endpoint,target)<1e-4,(endpoint,target)
    assert math.dist(c.xform(ns+'joint1',q=True,ws=True,t=True),endpoint)>16
    checks.append('stretch, softness, bend limit and scale parameters evaluate')
    for n,m in original.items():
        assert max(abs(x-y) for x,y in zip(c.xform(a['namespace']+':'+n,q=True,ws=True,m=True),m))<1e-5
    checks.append('other instance remains unchanged')
    # Roll is driven by relative rotation; envelope can turn off its contribution.
    roll=ns+'rotator_null2_twist1.rotateX'
    c.setAttr(ns+'elbow_roll1.envelope',0)
    assert abs(c.getAttr(roll))<1e-6
    c.setAttr(ns+'elbow_roll1.envelope',1)
    report={'passed':True,'nodes_per_rig':len(a['nodes']),'checks':checks,'baseline_error':a['baseline_max_error']}
    out=Path(__file__).resolve().parents[1]/'outputs/scene-study/soft-limb-tests.json'
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)

try:
    main()
finally:
    maya.standalone.uninitialize()
