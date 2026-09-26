"""Use copies of the open mannequin poses to validate the integrated constructor."""
import json,math,runpy,uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om


def verify():
    from maya_agent.rigs.integrated import build
    source={'body':['pelvis','spine_01','spine_02','spine_03'],'head':['neck_01','head']}
    for side in ('L','R'):
        suffix=side.lower()
        source['shoulder_'+side]=['clavicle_'+suffix]
        source['arm_'+side]=[n+'_'+suffix for n in ('upperarm','lowerarm','hand')]
        source['leg_'+side]=[n+'_'+suffix for n in ('thigh','calf','foot','ball')]
    for names in source.values():
        for n in names:assert c.objExists(n),n
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
    prefix='_actualReference_'+uuid.uuid4().hex[:7]
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    try:
        # Capture before fixture construction, from the user's unmodified rig.
        motion={}
        for f in range(31):
            c.currentTime(f);motion[f]={n:c.xform(n,q=True,ws=True,m=True) for names in source.values() for n in names}
        c.currentTime(0);parts={}
        for k,names in source.items():
            targets=[]
            for n in names:
                target=c.createNode('transform',name=prefix+'_'+n);targets.append(target);previous=None
                for f,poses in motion.items():
                    m=poses[n];tm=om.MTransformationMatrix(om.MMatrix(m));e=tm.rotation(asQuaternion=True).asEulerRotation()
                    if previous:e=e.closestSolution(previous)
                    previous=e
                    for a,v in zip(['translate'+x for x in 'XYZ']+['rotate'+x for x in 'XYZ'],m[12:15]+[math.degrees(v) for v in e]):
                        c.setKeyframe(target,at=a,t=f,v=v,itt='linear',ott='linear')
            parts[k]=dict(targets=targets,copy_animation=True,start_frame=0,end_frame=30)
        rig=build(parts,namespace=prefix)
        assert rig['max_world_error']<1e-4
        original_error=0.0
        for f,poses in motion.items():
            c.currentTime(f)
            for n,m in poses.items():original_error=max(original_error,max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
        assert original_error<1e-8,original_error
        return dict(passed=True,frames=31,parts=len(parts),copy_error=rig['max_world_error'],reference_unchanged_error=original_error)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
        for n,keys in curves.items():assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==keys
