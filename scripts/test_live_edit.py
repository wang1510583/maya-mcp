"""Behavioral regressions: test the motion, not merely the displayed matrix."""
import math
import uuid
import maya.cmds as c
import maya.api.OpenMaya as om
from scripts.test_integrated_rig_live import fixture, remove
from maya_agent.rigs import live_edit
from maya_agent.rigs.live_alignment import enable
from maya_agent.rigs.integrated import build


def verify(animated=False,spaces=False):
    before=set(c.ls(long=True));sel=c.ls(sl=True,long=True) or []
    frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    rig=None;out=[]
    try:
        c.autoKeyframe(state=False)
        prefix='_liveEditTest_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,animated)
        if spaces:
            for p in parts.values():p.update(space_upper_arm=True,space_wrist=True,space_foot=True,space_knee=True)
        c.currentTime(3 if animated else 1)
        rig=build({k:v for k,v in parts.items() if k.startswith(('arm','leg'))},namespace=prefix)
        for key,p in rig['parts'].items():
            d=enable(p,key.split('_')[0])
            if key.startswith('arm'):
                c.move(-.6 if key.endswith('L') else .6,.5,1,p['live_controls']['end_fk'],r=True,ws=True)
                c.rotate(17,-9,12,p['live_controls']['end_fk'],r=True,os=True)
                role='middle_fk';pivot_joint=p['joints'][1];end=p['joints'][2]
            else:
                c.setAttr(p['live_controls']['heel']+'.rx',-20)
                c.setAttr(p['live_controls']['toe_end']+'.rz',8)
                role='foot';pivot_joint=p['joints'][2];end=None
            control=p['live_controls'][role]
            # Clicking without moving may not reset heel/toe values or touch keys.
            c.select(control)
            originals=live_edit._snapshot([n+'.'+a for n in list(p['controls'].values())+list(p['live_controls'].values())
                                          if not c.objExists(n+'.liveInput') and n not in d['inputs'].values()
                                          for a in live_edit.TR if c.objExists(n+'.'+a) and not c.connectionInfo(n+'.'+a,sourceFromDestination=True)])
            allkeys={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),
                        c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True)) for n in c.ls(type='animCurve')}
            live_edit.before_drag('test');live_edit.after_drag('test')
            afterkeys={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),
                          c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True)) for n in c.ls(type='animCurve')}
            assert allkeys==afterkeys, [(n,v,afterkeys.get(n)) for n,v in allkeys.items() if v!=afterkeys.get(n)]
            assert all(abs(c.getAttr(n)-v)<1e-8 for n,v in originals[0].items())
            pose_error=0;pivot_error=0;axis_error=0
            for gesture in range(5):
                matrices={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
                live_edit.prepare(p['root'])
                pose_error=max(pose_error,max(abs(a-b) for n,m in matrices.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
                origin=c.xform(pivot_joint,q=True,ws=True,t=True)
                if end: endpoint=c.xform(end,q=True,ws=True,t=True)
                basis=om.MMatrix(c.xform(control,q=True,ws=True,m=True))
                rotation=om.MEulerRotation(0,0,math.radians(7)).asMatrix()
                delta=basis.inverse()*rotation*basis
                c.rotate(0,0,7,control,r=True,os=True)
                pivot_error=max(pivot_error,math.dist(origin,c.xform(pivot_joint,q=True,ws=True,t=True)))
                if end:
                    expected=om.MPoint(endpoint)*delta
                    axis_error=max(axis_error,math.dist(list(expected)[:3],c.xform(end,q=True,ws=True,t=True)))
            out.append(dict(part=key,animated=animated,spaces=spaces,rebase_pose_error=pose_error,rotation_pivot_error=pivot_error,endpoint_axis_error=axis_error))
            assert pose_error<1e-5, out[-1]
            assert pivot_error<1e-5, out[-1]
            assert axis_error<1e-5, out[-1]
        return out
    finally:
        if rig:remove(rig)
        for node in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(node):c.delete(node)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(cl=True)
