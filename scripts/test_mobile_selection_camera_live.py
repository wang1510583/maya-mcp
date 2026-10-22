"""Disposable export fixture; preserves the user's open Maya scene."""
import json,runpy,importlib,sys
from pathlib import Path
import maya.cmds as c

ROOT=Path(__file__).resolve().parents[1]
BACK=ROOT/'自定义人物绑定插件/maya_agent/rigs/mobile_io/backend'
OUT=ROOT/'outputs/selection-camera-053'

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    snapshot=runpy.run_path(str(BACK/'export_snapshot.py'));before=snapshot['fingerprint']()
    matrices={n:c.xform(n,q=True,ws=True,m=True) for n in (c.ls(type='transform',long=True) or [])+(c.ls(type='joint',long=True) or [])}
    ns='mobileExportCameraTest'
    if c.namespace(exists=ns):raise RuntimeError('Fixture namespace already exists')
    previous=c.namespaceInfo(currentNamespace=True);c.namespace(add=ns);c.namespace(set=ns)
    try:
        root=c.createNode('transform',name='rig');ctrl=c.circle(name='control',ch=False)[0];c.parent(ctrl,root)
        j=c.createNode('joint',name='joint');j2=c.createNode('joint',name='joint2',parent=j);c.setAttr(j2+'.ty',3)
        body=c.polyCube(name='body',ch=False,w=3,h=5,d=2)[0];c.skinCluster([j,j2],body,tsb=True,name='skin')
        c.parentConstraint(ctrl,j,mo=True)
        meta=dict(namespace=ns,version='camera-test',master_control=ctrl,parts={'fixture':dict(root=root,controls={},original_target_mapping=[dict(target=j)])})
        c.addAttr(root,ln='integratedRigData',dt='string');c.setAttr(root+'.integratedRigData',json.dumps(meta),type='string')
        extra=c.polyCube(name='extra',ch=False)[0];c.setAttr(extra+'.tx',5)
        extra_joint=c.createNode('joint',name='extra_joint');c.setAttr(extra_joint+'.ty',7)
        extra_skin_mesh=c.polyCube(name='extra_skinned',ch=False)[0];c.setAttr(extra_skin_mesh+'.ty',7);c.skinCluster([extra_joint],extra_skin_mesh,tsb=True,name='extra_skin')
        for f,v in [(0,7),(2,9)]:c.setKeyframe(extra_joint,at='ty',t=f,v=v)
        unrelated=c.polyCube(name='excluded',ch=False)[0]
        cam,shape=c.camera(name='shot');c.setAttr(cam+'.tz',20);c.setAttr(cam+'.rz',17);c.setAttr(shape+'.horizontalFilmOffset',.08)
        for f,v in [(0,20),(2,24)]:c.setKeyframe(cam,at='tz',t=f,v=v)
        for f,v in [(0,35),(2,50)]:c.setKeyframe(shape,at='focalLength',t=f,v=v)
        for f,v in [(0,5),(2,8)]:c.setKeyframe(extra,at='tx',t=f,v=v)
        ortho,ortho_shape=c.camera(name='ortho');c.setAttr(ortho+'.tz',20);c.setAttr(ortho_shape+'.orthographic',True);c.setAttr(ortho_shape+'.orthographicWidth',14)
        c.currentTime(0);c.select([extra,extra_joint,extra_skin_mesh,cam,ortho],r=True)
        selected=c.ls(sl=True,long=True);fixture_before=snapshot['fingerprint']()
        select=runpy.run_path(str(BACK/'export_selection.py'))['resolve']
        assert select(root,[])==dict(meshes=[],joints=[],cameras=[],selection=[])
        assert select(root,[extra])['meshes']
        assert select(root,[cam])['cameras']
        assert not select(root,[ctrl])['meshes']
        for invalid in [[extra+'.vtx[0]'],['missing_export_test_object']]:
            try:select(root,invalid)
            except ValueError:pass
            else:raise AssertionError('Invalid selection accepted')
        baseline_path=OUT/'character-only.json'
        if baseline_path.exists():baseline_path.unlink()
        snapshot['export'](root,str(baseline_path),selection=[])
        baseline=json.loads(baseline_path.read_text('utf8'))
        assert len(baseline['meshes'])==1 and baseline['controls']
        for label,items,count,camera_count in [('only-model',[extra],2,0),('only-camera',[cam],1,1),('rig-and-model',[ctrl,extra],2,0)]:
            path=OUT/(label+'.json')
            if path.exists():path.unlink()
            snapshot['export'](root,str(path),selection=items)
            case=json.loads(path.read_text('utf8'))
            assert len(case['meshes'])==count and len(case['exportSelection']['cameras'])==camera_count
            assert {r['id'] for r in baseline['controls']} <= {r['id'] for r in case['controls']}
        from maya_agent.rigs.mobile_io import service
        importlib.reload(service)
        target=OUT/'selection-camera.mobile.json'
        if target.exists():target.unlink()
        report=service.export_project(root,str(target),True,0,2,selection=selected)
        package=json.loads(target.read_text('utf8'));snap=json.loads(package['snapshotJson'])
        assert len(snap['meshes'])==3 and len(snap['cameras'])==2
        assert not any('excluded' in m['name'] for m in snap['meshes'])
        assert any('extra_joint' in j['name'] for j in snap['joints'])
        assert len(snap['cameras'][0]['samples']) in (1,3)
        assert all(snapshot['fingerprint']()[k]==fixture_before[k] for k in fixture_before if k!='transformsHash')
        (OUT/'snapshot.json').write_text(package['snapshotJson'],'utf8')
        compiler=runpy.run_path(str(BACK/'export_portable_graph.py'))
        compiler['export'](str(OUT/'snapshot.json'),str(OUT/'debug.json'))
        compiler['compact'](str(OUT/'debug.json'),str(OUT/'graph.json'))
        for filename in ('animation.json','reference.json'):
            p=OUT/filename
            if p.exists():p.unlink()
        runpy.run_path(str(BACK/'export_animation.py'))['export'](str(OUT/'snapshot.json'),str(OUT/'graph.json'),str(OUT/'animation.json'),str(OUT/'reference.json'))
        (OUT/'report.json').write_text(json.dumps(report,indent=2),'utf8')
        print(json.dumps(dict(passExport=True,meshes=3,cameras=2,extraJoint=True,excludedUnselected=True,project=str(target))))
    finally:
        c.namespace(set=previous);c.namespace(removeNamespace=ns,deleteNamespaceContent=True)
        c.currentTime(before['frame']);c.select(before['selection'],r=True) if before['selection'] else c.select(clear=True)
        c.file(modified=before['modified']);c.refresh(force=True)
        after=snapshot['fingerprint']()
        error=max((abs(a-b) for n,m in matrices.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))),default=0.)
        restored=all(before[k]==after[k] for k in before if k!='transformsHash') and error<1e-8
        (OUT/'restoration.json').write_text(json.dumps(dict(restored=restored,exact=before==after,maxMatrixError=error,differences=[k for k in before if before[k]!=after[k]]),indent=2),'utf8')
        assert restored,'User scene restoration mismatch'

if __name__=='__main__':run()
