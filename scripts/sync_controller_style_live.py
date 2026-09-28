"""Explicit left-to-right artwork authoring for a symmetric, already posed rig.

Edits CV/display attributes only, preserving shape identities and solver graphs.
Requires matching curve topology and symmetric local axes; aborts before editing
otherwise. This is an authoring utility, never a build-time scene dependency.
"""
import copy
import json
from datetime import datetime
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om
import maya.mel as mel
from maya_agent.rigs import controller_shapes as art


def _shapes(node):
    return [s for s in c.listRelatives(node,s=True,f=True) or []
            if c.nodeType(s) in ('nurbsCurve','locator') and c.getAttr(s+'.lodVisibility')]


def _write(node, artwork):
    scale=om.MTransformationMatrix(om.MMatrix(c.xform(node,q=True,ws=True,m=True))).scale(om.MSpace.kWorld)
    pivot=c.xform(node,q=True,os=True,rp=True)
    art._set_display(node,artwork['display'])
    if 'joint' in artwork:
        c.setAttr(node+'.drawStyle',artwork['joint']['drawStyle'])
        c.setAttr(node+'.radius',artwork['joint']['radius']/abs(scale[0]))
    for shape,item in zip(_shapes(node),artwork['shapes']):
        # xform on periodic CVs propagates seam edits. Replace the complete
        # curve data atomically instead, retaining this shape's node identity.
        points=[[pivot[a]+point[a]/scale[a] for a in range(3)] for point in item['points']]
        values=[str(item['degree']),str(len(points)-item['degree']),str(item['form']-1),
                'no','3',str(len(item['knots']))]
        values += [str(v) for v in item['knots']]+[str(len(points))]
        values += [str(v) for p in points for v in p]
        mel.eval('setAttr '+json.dumps(shape+'.cc')+' -type "nurbsCurve" '+' '.join(values)+';')
        art._set_display(shape,item['display'])
        c.setAttr(shape+'.visibility',item['visibility'])


def sync(root):
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    template_text=art.DATA.read_text(encoding='utf-8')
    template=json.loads(template_text)
    reflection=om.MMatrix([-1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1])
    plans=[];left_snapshots={};right_snapshots={};maps={}
    for kind in ('shoulder','arm','leg'):
        left=rig['parts'][kind+'_L'];right=rig['parts'][kind+'_R']
        for side,part in (('L',left),('R',right)):
            template['parts'][kind+'_'+side]['metrics']=art.measure(kind+'_'+side,[m['target'] for m in part['original_target_mapping']])
        for role,input_node in left['controls'].items():
            if role in art.HELPERS:continue
            node=left.get('live_controls',{}).get(role,input_node)
            destination=right.get('live_controls',{}).get(role,right['controls'][role])
            source=art.capture_control(node);old=art.capture_control(destination)
            assert len(source['shapes'])==len(old['shapes']),(kind,role,'shape count')
            for a,b,s in zip(source['shapes'],old['shapes'],_shapes(destination)):
                assert a['type']==b['type']=='nurbsCurve',(kind,role,'non-curve artwork')
                assert (a['degree'],a['form'],a['knots'],len(a['points']))==(b['degree'],b['form'],b['knots'],len(b['points'])),(kind,role,'topology')
                assert not c.listConnections(s+'.create',s=True,d=False),(s,'driven curve')
                assert not c.listConnections(s+'.controlPoints',s=True,d=False),(s,'driven CV')
                assert all(abs(p[3]-1)<1e-10 for p in a['points']+b['points']),'weighted CVs'
            rotations=[om.MTransformationMatrix(om.MMatrix(c.xform(n,q=True,ws=True,m=True))).rotation(asQuaternion=True).asMatrix() for n in (node,destination)]
            matrix=rotations[0]*reflection*rotations[1].inverse()
            signs=[1 if matrix[i*4+i]>0 else -1 for i in range(3)]
            assert max(abs(matrix[i*4+j]-(signs[i] if i==j else 0)) for i in range(3) for j in range(3))<1e-3,(kind,role,'asymmetric axes')
            desired=copy.deepcopy(source)
            for item in desired['shapes']:
                for p in item['points']:
                    for i in range(3):p[i]*=signs[i]
            maps[kind+'.'+role]=signs
            plans.append((destination,desired))
            left_snapshots[node]=source;right_snapshots[destination]=old
            template['parts'][kind+'_L']['controls'][role]=source
            template['parts'][kind+'_R']['controls'][role]=desired
    directory=Path(__file__).resolve().parents[1]/'outputs/controller-shapes'/datetime.now().strftime('sync-left-%Y%m%d-%H%M%S')
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'template-before.json').write_text(template_text,encoding='utf-8')
    (directory/'scene-before.json').write_text(json.dumps(dict(left=left_snapshots,right=right_snapshots),indent=2),encoding='utf-8')
    dag=c.ls(type='transform',long=True)+c.ls(type='joint',long=True)
    poses={n:c.xform(n,q=True,ws=True,m=True) for n in dag}
    curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
    auto=c.autoKeyframe(q=True,state=True)
    c.undoInfo(openChunk=True,chunkName='SyncRightControllerArtwork')
    try:
        c.autoKeyframe(state=False)
        for node,desired in plans:_write(node,desired)
        pose_error=max(abs(a-b) for n,m in poses.items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
        assert pose_error<1e-9,pose_error
        assert curves=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        assert all(art.capture_control(n)==old for n,old in left_snapshots.items()),'left changed'
        max_error=0
        for n,desired in plans:
            actual=art.capture_control(n)
            assert actual['display']==desired['display']
            for a,b in zip(actual['shapes'],desired['shapes']):
                assert a['display']==b['display']
                max_error=max(max_error,max(abs(v-w) for p,q in zip(a['points'],b['points']) for v,w in zip(p,q)))
        assert max_error<1e-8,max_error
        template['version']=art.VERSION
        template['style_source']='left_authoritative_20260927'
        template['right_local_reflection']=maps
        pending=directory/'template-after.json'
        pending.write_text(json.dumps(template,ensure_ascii=False,indent=2),encoding='utf-8')
        art.DATA.write_text(pending.read_text(encoding='utf-8'),encoding='utf-8')
        report=dict(controls=len(plans),max_cv_error=max_error,pose_error=pose_error,
                    left_unchanged=True,animation_unchanged=True,backup=str(directory),template=str(art.DATA))
        (directory/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
    except Exception:
        for node,old in right_snapshots.items():_write(node,old)
        art.DATA.write_text(template_text,encoding='utf-8')
        raise
    finally:
        c.autoKeyframe(state=auto)
        c.undoInfo(closeChunk=True)
