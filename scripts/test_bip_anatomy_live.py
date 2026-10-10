"""Independent world-position, foot-sole and shoulder-plane checks in Maya.

Expected motion comes directly from native Max matrices. Does not call plan,
the production anatomical frames, or the controller baker.
"""
import json
import math
from pathlib import Path


def run(path,root,output_start=0):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    rest=json.loads(c.getAttr(root+'.bipRetargetCalibration'))['rest']
    labels={'body':['Pelvis','Spine','Spine1','Spine2'],'head':['Neck','Head']}
    for s in ('L','R'):
        labels['shoulder_'+s]=[s+' Clavicle']
        labels['arm_'+s]=[s+' '+a for a in ('UpperArm','Forearm','Hand')]
        labels['leg_'+s]=[s+' '+a for a in ('Thigh','Calf','Foot','Toe0')]
    target={label:row['target'] for key,p in rig['parts'].items() for label,row in zip(labels[key],p['original_target_mapping'])}
    def matrix(m):
        return om.MMatrix([x for row in m[:3] for x in [*row,0.]]+[*m[3],1.])
    def position(m):return om.MVector(list(m)[12:15])
    def rot(m):return om.MTransformationMatrix(m).rotation(asQuaternion=True).asMatrix()
    coord=om.MMatrix([1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1])
    refs={n:matrix(data['reference'][data['root']+' '+n])*coord for n in target}
    tr={n:om.MMatrix(rest[t]) for n,t in target.items()}
    a=position(refs['L Thigh'])-position(refs['R Thigh']);a.y=0
    b=position(tr['L Thigh'])-position(tr['R Thigh']);b.y=0
    coord*=a.rotateTo(b).asMatrix()
    refs={n:matrix(data['reference'][data['root']+' '+n])*coord for n in target}
    origin=position(tr['Pelvis'])-position(refs['Pelvis'])
    initial=position(matrix(data['samples'][0]['bones'][data['root']+' Pelvis'])*coord)
    origin.x=position(tr['Pelvis']).x-initial.x;origin.z=position(tr['Pelvis']).z-initial.z
    up=om.MVector(0,1,0);local={}
    for side in ('L','R'):
        foot=side+' Foot';local[foot]=(up*rot(tr[foot]).inverse(),up*rot(refs[foot]).inverse())
        clavicle,arm=side+' Clavicle',side+' UpperArm'
        # A shoulder plane has the clavicle aim and upright torso direction.
        tn=((position(tr[arm])-position(tr[clavicle]))^up).normal()
        sn=((position(refs[arm])-position(refs[clavicle]))^up).normal()
        local[clavicle]=(tn*rot(tr[clavicle]).inverse(),sn*rot(refs[clavicle]).inverse())
    old=c.currentTime(q=True);mode=c.evaluationManager(q=True,mode=True)[0]
    report={};fps=om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
    try:
        for evaluation in ('off','parallel'):
            c.evaluationManager(mode=evaluation)
            positions={n:0. for n in target};angles={n:0. for n in local};solver=0.
            for sample in data['samples']:
                f=output_start+(sample['frame']-data['samples'][0]['frame'])*fps/data['fps'];c.currentTime(f)
                for n,t in target.items():
                    actual=om.MMatrix(c.xform(t,q=True,ws=True,m=True))
                    source=matrix(sample['bones'][data['root']+' '+n])*coord
                    positions[n]=max(positions[n],(position(actual)-position(source)-origin).length())
                    if n in local:
                        x,y=local[n];x=(x*rot(actual)).normal();y=(y*rot(source)).normal()
                        angles[n]=max(angles[n],math.degrees(math.acos(max(-1.,min(1.,x*y)))))
                for key,p in rig['parts'].items():
                    if not key.startswith(('arm','leg')):continue
                    for row,j in zip(p['original_target_mapping'],p['joints']):
                        solver=max(solver,math.dist(c.xform(row['target'],q=True,ws=True,t=True),c.xform(j,q=True,ws=True,t=True)))
            report[evaluation]={'position_cm':positions,'orientation_degrees':angles,'solver_output_cm':solver}
        report['bone_keys']=sum(c.keyframe(t,q=True,kc=True) or 0 for t in target.values())
        report['skin_clusters']=c.ls(type='skinCluster')
        return report
    finally:
        c.currentTime(old);c.evaluationManager(mode=mode)
