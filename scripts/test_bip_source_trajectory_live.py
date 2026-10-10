"""Independent ankle-trajectory regression against raw Max capture matrices.

Run in Maya: run(capture_path, character_root). Does not use retarget.plan to
derive expected positions. Include subframes absent from the baked curves.
"""
import json
import math
from pathlib import Path


def run(path,root,tolerance=.025,output_start=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    data=json.loads(Path(path).read_text(encoding='utf8'))
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    rest=json.loads(c.getAttr(root+'.bipRetargetCalibration'))['rest']
    targets={k:[r['target'] for r in p['original_target_mapping']] for k,p in rig['parts'].items()}
    prefix=data['root']+' '
    def converted(matrix):
        x,y,z=matrix[3]
        return om.MVector(x,z,-y)
    def pos(matrix):return om.MVector(matrix[12:15])
    source_hips=[converted(data['reference'][prefix+s+' Thigh']) for s in ('L','R')]
    target_hips=[pos(rest[targets['leg_'+s][0]]) for s in ('L','R')]
    a=source_hips[0]-source_hips[1];b=target_hips[0]-target_hips[1];a.y=b.y=0
    heading=a.rotateTo(b)
    source_length=target_length=0
    for side in ('L','R'):
        points=[converted(data['reference'][prefix+side+' '+n]) for n in ('Thigh','Calf','Foot')]
        source_length+=sum((y-x).length() for x,y in zip(points,points[1:]))
        points=[pos(rest[n]) for n in targets['leg_'+side][:3]]
        target_length+=sum((y-x).length() for x,y in zip(points,points[1:]))
    scale=target_length/source_length
    origin=pos(rest[targets['body'][0]])-converted(data['reference'][prefix+'Pelvis']).rotateBy(heading)*scale
    first=data['samples'][0]['frame'];start=first if output_start is None else output_start
    fps=om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
    old=c.currentTime(q=True);mode=c.evaluationManager(q=True,mode=True)[0]
    report={}
    try:
        for evaluation in ('off','parallel'):
            c.evaluationManager(mode=evaluation)
            stats={s:dict(max_position_error_cm=0,max_planted_step_cm=0,
                          max_source_planted_step_cm=0,planted_steps=0,
                          max_solver_position_error_cm=0,max_bone_length_error_cm=0) for s in ('L','R')}
            previous={}
            for sample in data['samples']:
                frame=start+(sample['frame']-first)*fps/data['fps'];c.currentTime(frame)
                for side in ('L','R'):
                    target=targets['leg_'+side][2]
                    expected=converted(sample['bones'][prefix+side+' Foot']).rotateBy(heading)*scale+origin
                    actual=om.MVector(c.xform(target,q=True,ws=True,t=True));s=stats[side]
                    s['max_position_error_cm']=max(s['max_position_error_cm'],(actual-expected).length())
                    if side in previous:
                        prev_actual,prev_expected=previous[side]
                        source_step=(expected-prev_expected).length()
                        if source_step<.01:
                            s['planted_steps']+=1
                            s['max_planted_step_cm']=max(s['max_planted_step_cm'],(actual-prev_actual).length())
                            s['max_source_planted_step_cm']=max(s['max_source_planted_step_cm'],source_step)
                    previous[side]=(actual,expected)
                    part=rig['parts']['leg_'+side]
                    points=[om.MVector(c.xform(n,q=True,ws=True,t=True)) for n in targets['leg_'+side][:3]]
                    for joint,point in zip(part['joints'][:3],points):
                        err=(om.MVector(c.xform(joint,q=True,ws=True,t=True))-point).length()
                        s['max_solver_position_error_cm']=max(s['max_solver_position_error_cm'],err)
                    rest_points=[pos(rest[n]) for n in targets['leg_'+side][:3]]
                    for i in (0,1):
                        err=abs((points[i+1]-points[i]).length()-(rest_points[i+1]-rest_points[i]).length())
                        s['max_bone_length_error_cm']=max(s['max_bone_length_error_cm'],err)
            report[evaluation]=stats
        report['target_key_count']=sum(c.keyframe(n,q=True,kc=True) or 0 for n in rest)
        report['skin_clusters']=c.ls(type='skinCluster') or []
        for evaluation in ('off','parallel'):
            for side,s in report[evaluation].items():
                assert s['max_position_error_cm']<tolerance,(evaluation,side,s)
                assert s['max_solver_position_error_cm']<1e-5,(evaluation,side,s)
                assert s['max_bone_length_error_cm']<1e-5,(evaluation,side,s)
        assert report['target_key_count']==0,report['target_key_count']
        return report
    finally:
        c.currentTime(old);c.evaluationManager(mode=mode)
