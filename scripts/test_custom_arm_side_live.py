"""Right-side animated arm names, baking, and the original Easy Rig MEL."""
from pathlib import Path
import runpy
import maya.cmds as c
from maya_agent.rigs.soft_limb import build_from_selection


def verify():
    original=set(c.ls(long=True))
    checked=[]
    def create(**options):
        rig=build_from_selection(side='R',**options)
        ns=rig['namespace']+':'
        assert rig['side']=='R'
        assert rig['controls']['shoulder_fk']==ns+'shldrFK_R1'
        assert rig['controls']['middle_fk']==ns+'armFK_R1'
        assert rig['controls']['end_fk']==ns+'handFK_R1'
        assert all(c.objExists(n) for n in rig['nodes'])
        assert not [n for n in c.ls(ns+'*') if '_L' in n.split(':')[-1]]
        assert all(c.objExists(n) for n in rig['animation_transfer']['controls'])
        connections=c.listConnections(ns+'recalculate_node',connections=True,plugs=True) or []
        assert len(connections)==28
        assert ns+'armFK_R1.visibility' in connections
        checked.append(rig['side'])
        return rig
    run_case=runpy.run_path(str(Path(__file__).with_name('test_custom_arm_animation_live.py')))['run_case']
    run_case.__globals__['build']=create
    report=run_case(3,True,False,True,True)
    assert checked==['R']
    assert set(c.ls(long=True))==original
    try:build_from_selection(targets=[],side='invalid')
    except ValueError:pass
    else:raise AssertionError('Invalid side accepted')
    assert set(c.ls(long=True))==original
    return {'passed':True,'right_side_names_and_metadata':True,'invalid_side_rejected':True,'animation':report}
