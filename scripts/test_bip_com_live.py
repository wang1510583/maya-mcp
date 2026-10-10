"""Compare visible hips motion with the actual Max COM, not Pelvis or plan()."""
import json
import math
from pathlib import Path


def run(path,root,start=0):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    rig=json.loads(c.getAttr(root+'.integratedRigData'));body=rig['parts']['body']
    cal=json.loads(c.getAttr(root+'.bipRetargetCalibration'))
    pelvis=body['original_target_mapping'][0]['target'];hips=body['controls']['hips']
    visible=body['zero_controls']['hips']
    def matrix(m):return om.MMatrix([v for row in m[:3] for v in [*row,0.]]+[*m[3],1.])
    def pos(m):return om.MVector(list(m)[12:15])
    def rot(m):return om.MTransformationMatrix(m).rotation(asQuaternion=True).asMatrix()
    coord=om.MMatrix([1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1])
    lp=cal['rest'][rig['parts']['leg_L']['original_target_mapping'][0]['target']][12:15]
    rp=cal['rest'][rig['parts']['leg_R']['original_target_mapping'][0]['target']][12:15]
    refs=data['reference'];prefix=data['root']
    a=pos(matrix(refs[prefix+' L Thigh'])*coord)-pos(matrix(refs[prefix+' R Thigh'])*coord);a.y=0
    b=om.MVector(lp)-om.MVector(rp);b.y=0
    coord*=a.rotateTo(b).asMatrix()
    rest_hips=om.MMatrix(cal['offsets'][hips]).inverse()*om.MMatrix(cal['rest'][pelvis])
    offset=rot(rest_hips)*rot(matrix(refs[prefix])*coord).inverse()
    origin=om.MVector(cal['rest'][pelvis][12:15])-pos(matrix(refs[prefix+' Pelvis'])*coord)
    first=pos(matrix(data['samples'][0]['bones'][prefix+' Pelvis'])*coord)
    origin.x=cal['rest'][pelvis][12]-first.x;origin.z=cal['rest'][pelvis][14]-first.z
    fps=om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
    old=c.currentTime(q=True);report={};mode=c.evaluationManager(q=True,mode=True)[0]
    try:
        for evaluation in ['off','parallel']:
            c.evaluationManager(mode=evaluation);pe=ae=0.
            for sample in data['samples']:
                c.currentTime(start+(sample['frame']-data['samples'][0]['frame'])*fps/data['fps'])
                com=matrix(sample['bones'][prefix])*coord
                actual=om.MMatrix(c.xform(visible,q=True,ws=True,m=True))
                pe=max(pe,(pos(actual)-pos(com)-origin).length())
                q=om.MTransformationMatrix(rot(actual)*(offset*rot(com)).inverse()).rotation(asQuaternion=True)
                ae=max(ae,math.degrees(2*math.acos(min(1.,abs(q.w)))))
            report[evaluation]=dict(position_cm=pe,rotation_degrees=ae)
        report['visible']=visible
        report['pelvis_channels']=[n for n in c.listAttr(visible,keyable=True) if n.startswith('bipPelvis')]
        return report
    finally:c.currentTime(old);c.evaluationManager(mode=mode)
