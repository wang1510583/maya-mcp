"""Construct the previous bug from its development backup and migrate it."""
import importlib.util
from pathlib import Path
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_alignment,live_rotation_migration


def verify():
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);rig=None
    try:
        c.autoKeyframe(state=False)
        prefix='_legacyRotation_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,False)
        rig=build({'arm_L':parts['arm_L']},namespace=prefix)
        p=rig['parts']['arm_L'];d=live_alignment.enable(p,'arm')
        # Integrated metadata may predate manual enabling, just as older files do.
        import json
        data=json.loads(c.getAttr(rig['root']+'.integratedRigData'))
        data['parts']['arm_L'].update(live_controls=d['controls'])
        c.setAttr(rig['root']+'.integratedRigData',lock=False)
        c.setAttr(rig['root']+'.integratedRigData',json.dumps(data),type='string',lock=True)
        ctrl=d['controls']['middle_fk'];wrist=d['controls']['end_fk']
        c.move(-.6,.5,1,wrist,r=True,ws=True)
        for t in (6,8,12):
            c.setKeyframe(ctrl,at=['tx','ty','tz','rx','ry','rz'],time=t)
            c.setKeyframe(wrist,at=['tx','ty','tz'],time=t)
        path=Path(__file__).resolve().parents[1]/'outputs/live_rotation_v186_backup.py'
        spec=importlib.util.spec_from_file_location('maya_agent.rigs._old_rotation_test',path)
        legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
        for t,angle in ((6,15),(8,-20),(12,30),(8,6)):
            c.currentTime(t)
            c.move(.1,-.05,.03,wrist,r=True,ws=True);c.setKeyframe(wrist,at=['tx','ty','tz'],time=t)
            legacy.install(p['root'],'middle_fk')
            c.rotate(0,0,angle,ctrl,r=True,os=True)
            c.setKeyframe(ctrl,at=['rx','ry','rz'],time=t)
        report=live_rotation_migration.repair_character(rig['root'],str(path.parent/'repair-backups'))
        assert not c.ls(p['namespace']+':rotation_*')
        assert report['key_pose_error']<1e-5
        c.cutKey(list(d['controls'].values()),clear=True)
        baseline={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
        error=0
        for t in (0,6,7,8,9,10,12,16):
            c.currentTime(t)
            error=max(error,max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
        assert error<1e-5,error
        return dict(report,after_delete_motion=error)
    finally:
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(cl=True)
