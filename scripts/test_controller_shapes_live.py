"""Live artwork checks using disposable rigs; never opens or replaces a scene."""
import json
import math
import uuid
import maya.cmds as c
import maya.api.OpenMaya as om
from scripts.test_integrated_rig_live import fixture, remove


def _points(shape, node):
    selection=om.MSelectionList();selection.add(shape)
    fn=om.MFnNurbsCurve(selection.getDagPath(0))
    pivot=c.xform(node,q=True,os=True,rp=True)
    return [[p[i]-pivot[i] for i in range(3)] for p in fn.cvPositions()]


def verify(source_root):
    from maya_agent.rigs.integrated import build
    source=json.loads(c.getAttr(source_root+'.integratedRigData'))
    prefix='_artRegression_'+uuid.uuid4().hex[:7]
    time=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    nodes={m['target'] for p in source['parts'].values() for m in p['original_target_mapping']}
    nodes.update(n for p in source['parts'].values() for n in p['controls'].values())
    before={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    source_curves={}
    for key,part in source['parts'].items():
        for role,node in part['controls'].items():
            source_curves[key,role]=[_points(s,node) for s in c.listRelatives(node,s=True,f=True,type='nurbsCurve') or []
                                     if c.getAttr(s+'.lodVisibility')]
    reports=[]
    try:
        for scale in (.5,1,2):
            rig=None;group=c.createNode('transform',name=prefix+'_fixture')
            try:
                originals=sorted({m['target'] for p in source['parts'].values() for m in p['original_target_mapping']},key=lambda n:n.count('|'))
                copies={}
                for i,node in enumerate(originals):
                    ancestors=[n for n in copies if node.startswith(n+'|')]
                    parent=copies[max(ancestors,key=len)] if ancestors else group
                    clone=c.createNode('joint',name=prefix+'_target'+str(i),parent=parent)
                    matrix=list(before[node]);matrix[12:15]=[v*scale for v in matrix[12:15]]
                    c.xform(clone,ws=True,m=matrix);copies[node]=clone
                parts={k:dict(targets=[copies[m['target']] for m in p['original_target_mapping']]) for k,p in source['parts'].items()}
                rig=build(parts,namespace=prefix)
                largest=0;count=0
                for key,part in rig['parts'].items():
                    for role,info in part['appearance']['controls'].items():
                        shapes=[s for s in info['shapes'] if c.nodeType(s)=='nurbsCurve']
                        reference=source_curves[key,role]
                        assert len(shapes)==len(reference),(key,role)
                        for s,expected in zip(shapes,reference):
                            actual=_points(s,part['controls'][role])
                            assert len(actual)==len(expected)
                            error=max(abs(v-scale*w) for p,q in zip(actual,expected) for v,w in zip(p,q))
                            largest=max(largest,error)
                            assert error<1e-4,(key,role,error)
                        count+=1
                assert rig['max_world_error']<1e-4
                reports.append(dict(scale=scale,controls=count,max_cv_error=largest,pose_error=rig['max_world_error']))
            finally:
                if rig:remove(rig)
                if c.objExists(group):c.delete(group)
        assert all(max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))<1e-8 for n,m in before.items())
        return dict(cases=reports,source_unchanged=True)
    finally:
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)


def verify_animation_and_pivots():
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs.soft_leg import set_adjustment_mode
    prefix='_artAnimation_'+uuid.uuid4().hex[:7]
    frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    rig=None;group=None
    try:
        group,parts=fixture(prefix,animated=True,shoulders=True)
        c.currentTime(1)
        rig=build(parts,namespace=prefix)
        sample_frames=(1,1.5,2.7,3,4.5,5)
        outputs=[n for p in parts.values() for n in p['targets']]
        for side in ('L','R'):
            leg=rig['parts']['leg_'+side];foot=leg['controls']['heel']
            for f,value in ((1,0),(3,25),(5,-15)):c.setKeyframe(foot,at='rotateX',t=f,v=value)
        baseline={}
        for f in sample_frames:
            c.currentTime(f);baseline[f]={n:c.xform(n,q=True,ws=True,m=True) for n in outputs}
        c.currentTime(3)
        artwork_error=0
        for side in ('L','R'):
            leg=rig['parts']['leg_'+side]
            mode=set_adjustment_mode(leg,True)
            before={r:[_points(s,leg['controls'][r]) for s in leg['appearance']['controls'][r]['shapes'] if c.nodeType(s)=='nurbsCurve'] for r in ('heel','toe_end','toe')}
            for guide in mode['guides'].values():c.move(.3,.6,-.2,guide,relative=True,worldSpace=True)
            set_adjustment_mode(leg,False)
            for r,expected in before.items():
                shapes=[s for s in leg['appearance']['controls'][r]['shapes'] if c.nodeType(s)=='nurbsCurve']
                for s,points in zip(shapes,expected):
                    error=max(abs(a-b) for p,q in zip(_points(s,leg['controls'][r]),points) for a,b in zip(p,q))
                    artwork_error=max(artwork_error,error)
        largest=0
        for f in sample_frames:
            c.currentTime(f)
            for n in outputs:largest=max(largest,max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),baseline[f][n])))
        assert largest<1e-4,largest
        assert artwork_error<1e-5,artwork_error
        return dict(copy_error=rig['max_world_error'],pivot_animation_error=largest,artwork_pivot_error=artwork_error)
    finally:
        if rig:remove(rig)
        if group and c.objExists(group):c.delete(group)
        # Transfer keeps source curves as backups; these fixture curves are now
        # disconnected after remove() and are owned by this test's unique prefix.
        for curve in c.ls(prefix+'*',type='animCurve') or []:
            assert not c.listConnections(curve,s=False,d=True),curve
            c.delete(curve)
        c.currentTime(frame)
        c.select(selection,r=True) if selection else c.select(clear=True)
