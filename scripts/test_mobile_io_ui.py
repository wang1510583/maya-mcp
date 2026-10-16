"""Run inside Maya: disposable import fixture, backup/undo and rejection checks."""
import json,hashlib,tempfile,uuid
from pathlib import Path
import maya.cmds as c

def run():
    from maya_agent.rigs.mobile_io import service
    fp=service.module('export_snapshot')['fingerprint'];before=fp();undo=c.undoInfo(q=True,state=True);root=None;report={}
    if not undo:raise RuntimeError('Enable Maya undo before the regression test')
    try:
        c.autoKeyframe(state=False);c.undoInfo(stateWithoutFlush=False)
        root=c.createNode('transform',name='mobileExchangeFixture_'+uuid.uuid4().hex[:8]);node=c.createNode('transform',name='control',parent=root)
        root=c.ls(root,long=True)[0];node=c.ls(node,long=True)[0];rid=c.ls(root,uuid=True)[0];uid=c.ls(node,uuid=True)[0]
        meta={'version':'fixture-1','parts':{'fixture':{'controls':{'control':node}}}}
        c.addAttr(root,longName='integratedRigData',dataType='string');c.setAttr(root+'.integratedRigData',json.dumps(meta),type='string')
        for frame,value in ((0,2),(10,4),(20,6)):c.setKeyframe(node+'.translateX',time=frame,value=value,itt='linear',ott='linear')
        original_times=c.keyframe(node+'.translateX',q=True,tc=True);original_values=c.keyframe(node+'.translateX',q=True,vc=True)
        c.undoInfo(stateWithoutFlush=True)
        with tempfile.TemporaryDirectory(prefix='mobile_io_test_') as directory:
            folder=Path(directory);snap={'characterId':rid,'rigVersion':'fixture-1'};raw=json.dumps(snap);digest=hashlib.sha256(raw.encode()).hexdigest()
            project={'format':'maya-mobile-project','snapshotJson':raw,'solver':{'characterId':rid,'sourceSnapshotSha256':digest}}
            source=folder/'source.mobile.json';source.write_text(json.dumps(project),'utf8')
            anim={'format':'maya-mobile-animation','schemaVersion':1,'characterId':rid,'rigVersion':'fixture-1','valueSpace':'local-absolute','interpolation':'maya-auto-ease','autoEaseControls':[uid],'curvePolicy':'replace-auto-ease-tracks','keys':[{'frame':f,'values':{uid:{'translateX':v}}} for f,v in ((0,7),(10,9))]}
            path=folder/'animation.json';path.write_text(json.dumps(anim),'utf8')
            preflight=service.import_animation(root,source,path,True)
            assert c.keyframe(node+'.translateX',q=True,vc=True)==original_values
            applied=service.import_animation(root,source,path,False)
            assert c.keyframe(node+'.translateX',q=True,tc=True)==[0.,10.]
            assert c.keyframe(node+'.translateX',q=True,vc=True)==[7.,9.]
            backup=json.loads(Path(applied['backup']).read_text('utf8'));assert backup['channels'][node+'.translateX']['values']==original_values
            c.undo();assert c.keyframe(node+'.translateX',q=True,tc=True)==original_times and c.keyframe(node+'.translateX',q=True,vc=True)==original_values
            report.update(preflightNoWrites=True,importValues=True,replacesEditedTrack=True,backupValues=True,undoRestored=True)
            c.undoInfo(stateWithoutFlush=False);c.setAttr(node+'.translateX',lock=True)
            try:service.import_animation(root,source,path,True)
            except ValueError:report['lockedRejected']=True
            else:raise AssertionError('Locked channel accepted')
            c.setAttr(node+'.translateX',lock=False)
            bad=json.loads(source.read_text('utf8'));bad['solver']['sourceSnapshotSha256']='bad';source.write_text(json.dumps(bad),'utf8')
            try:service.import_animation(root,source,path,True)
            except ValueError:report['hashRejected']=True
            else:raise AssertionError('Wrong hash accepted')
    finally:
        c.undoInfo(stateWithoutFlush=False)
        if root and c.objExists(root):c.delete(root)
        c.currentTime(before['frame']);c.select(before['selection'],replace=True) if before['selection'] else c.select(clear=True)
        c.autoKeyframe(state=before['autoKey']);c.file(modified=before['modified']);c.undoInfo(stateWithoutFlush=undo)
    after=fp();report['sceneUnchanged']=before==after
    if not report['sceneUnchanged']:raise AssertionError('Scene differs: '+str([k for k in before if before[k]!=after[k]]))
    return report
