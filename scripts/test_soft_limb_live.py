"""Exercise an existing replica and restore every edited control value afterwards."""
import json
import math
import maya.cmds as c
from maya_agent.rigs.soft_limb import DATA


def verify(namespace):
    spec=json.loads((DATA/'limb_v1.json').read_text(encoding='utf-8'))
    ns=namespace+':'
    def world(n): return c.xform(ns+n,q=True,ws=True,m=True)
    def position(n): return world(n)[12:15]
    changes=['armFK_L1.rotateZ','handFK_L1.translateX','strech_ik_foot1.lenght_coeff',
             'strech_ik_foot1.softness','strech_ik_foot1.full_straight_coeff',
             'strech_ik_foot1.bend_limit','strech_ik_foot1.scale_coeff','elbow_roll1.envelope',
             'elbow_roll1.rot_scale']
    values={a:c.getAttr(ns+a) for a in changes}
    baseline={n:world(n) for n in spec['world_matrices']}
    all_nodes=set(c.ls(long=True))
    scripts=set(c.ls(type='script'))
    selected=c.ls(sl=True,long=True) or []
    checks=[]
    try:
        for n in spec['nodes']+['rig_root', 'recalculate_node']:
            for other in c.listConnections(ns+n,s=True,d=True) or []:
                assert other.startswith(ns) or other=='time1',(n,other)
        checks.append('all rig connections are independent of the source scene')
        before=position('joint3')
        c.setAttr(ns+'armFK_L1.rotateZ',values['armFK_L1.rotateZ']-25)
        after=position('joint3')
        assert math.dist(before,after)>1,(before,after)
        for i,attr in ((1,'lenght_joint_1'),(2,'lenght_joint_2')):
            distance=math.dist(position('joint'+str(i)),position('joint'+str(i+1)))
            assert abs(distance-c.getAttr(ns+'strech_ik_foot1.'+attr))<1e-4,distance
        c.setAttr(ns+'armFK_L1.rotateZ',values['armFK_L1.rotateZ'])
        checks.append('FK bending drives output; original segment lengths preserved')
        roll=c.getAttr(ns+'rotator_null2_twist1.rotateX')
        c.setAttr(ns+'elbow_roll1.envelope',0)
        assert abs(c.getAttr(ns+'rotator_null2_twist1.rotateX'))<1e-6
        c.setAttr(ns+'elbow_roll1.envelope',values['elbow_roll1.envelope'])
        c.setAttr(ns+'elbow_roll1.rot_scale',values['elbow_roll1.rot_scale']*2)
        assert abs(c.getAttr(ns+'rotator_null2_twist1.rotateX')-roll*2)<1e-5
        c.setAttr(ns+'elbow_roll1.rot_scale',values['elbow_roll1.rot_scale'])
        checks.append('elbow rotation envelope and distribution multiplier')
        c.setAttr(ns+'handFK_L1.translateX',values['handFK_L1.translateX']+8)
        c.setAttr(ns+'strech_ik_foot1.lenght_coeff',.8)
        c.setAttr(ns+'strech_ik_foot1.softness',.2)
        c.setAttr(ns+'strech_ik_foot1.full_straight_coeff',.5)
        c.setAttr(ns+'strech_ik_foot1.bend_limit',.08)
        c.setAttr(ns+'strech_ik_foot1.scale_coeff',.5)
        for n in baseline: assert all(math.isfinite(v) for v in world(n)),n
        assert math.dist(position('joint3'),position('hand_L1'))<1e-4
        assert math.dist(position('joint1'),position('joint3'))>16
        assert c.getAttr(ns+'soft_knee_gr.translateY')>0
        checks.append('stretch and softness reach endpoint with finite bend-limited output')
    finally:
        for a,v in values.items(): c.setAttr(ns+a,v)
        for n,m in baseline.items():
            assert max(abs(a-b) for a,b in zip(world(n),m))<1e-4,n
        c.select(selected,r=True) if selected else c.select(clear=True)
        assert set(c.ls(long=True))==all_nodes
        assert set(c.ls(type='script'))==scripts
    return {'passed':True,'namespace':namespace,'checks':checks,'restored_original_pose':True,
            'no_script_nodes_added':True}
