"""Compare every Maya target directly with native Max Biped sample positions.

Expected positions come from raw captured matrices, not retarget.plan().
Use independent fractional samples to include times between baked keys.
"""
import json
import math
from pathlib import Path


def run(path,root,tolerance=.05,output_start=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from maya_agent.rigs.bip_retarget import ROLE_NAMES
    data=json.loads(Path(path).read_text(encoding='utf8'))
    assert data['native_retarget']['trajectory']=='native_biped_world'
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    rest=json.loads(c.getAttr(root+'.bipRetargetCalibration'))['rest']
    targets={k:[r['target'] for r in p['original_target_mapping']] for k,p in rig['parts'].items()}
    mapping={n:data['root']+' '+label for k,nodes in targets.items() for n,label in zip(nodes,ROLE_NAMES[k])}
    def source_point(matrix):
        x,y,z=matrix[3];return om.MVector(x,z,-y)
    a=source_point(data['reference'][mapping[targets['leg_L'][0]]])-source_point(data['reference'][mapping[targets['leg_R'][0]]])
    b=om.MVector(rest[targets['leg_L'][0]][12:15])-om.MVector(rest[targets['leg_R'][0]][12:15]);a.y=b.y=0
    heading=a.rotateTo(b)
    pelvis=targets['body'][0]
    origin=om.MVector(rest[pelvis][12:15])-source_point(data['reference'][mapping[pelvis]]).rotateBy(heading)
    initial=source_point(data['samples'][0]['bones'][mapping[pelvis]]).rotateBy(heading)
    origin.x=rest[pelvis][12]-initial.x;origin.z=rest[pelvis][14]-initial.z
    first=data['samples'][0]['frame'];start=first if output_start is None else output_start
    fps=om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
    old=c.currentTime(q=True);mode=c.evaluationManager(q=True,mode=True)[0];report={}
    try:
        for evaluation in ('off','parallel'):
            c.evaluationManager(mode=evaluation)
            errors={k:0 for k in targets};worst=None;max_error=0;ik_error=0
            for sample in data['samples']:
                f=start+(sample['frame']-first)*fps/data['fps'];c.currentTime(f)
                for k,nodes in targets.items():
                    for n in nodes:
                        actual=om.MVector(c.xform(n,q=True,ws=True,t=True))
                        expected=source_point(sample['bones'][mapping[n]]).rotateBy(heading)+origin
                        e=(actual-expected).length();errors[k]=max(errors[k],e)
                        if e>max_error:max_error=e;worst=[f,n]
                    if k.startswith(('arm','leg')):
                        for n,joint in zip(nodes,rig['parts'][k]['joints']):
                            e=math.dist(c.xform(n,q=True,ws=True,t=True),c.xform(joint,q=True,ws=True,t=True))
                            ik_error=max(ik_error,e)
            report[evaluation]=dict(max_position_error_cm=max_error,part_errors_cm=errors,
                                    worst=worst,max_solver_output_error_cm=ik_error)
            assert max_error<tolerance,report[evaluation]
            assert ik_error<.002,report[evaluation]
        report['target_keys']=sum(c.keyframe(n,q=True,kc=True) or 0 for n in rest)
        report['skin_clusters']=c.ls(type='skinCluster') or []
        assert report['target_keys']==0
        return report
    finally:c.currentTime(old);c.evaluationManager(mode=mode)
