"""Live disposable regression for final-check tolerance and rollback."""
import json
import runpy
import uuid
from pathlib import Path
import maya.cmds as c


def verify():
    from maya_agent.rigs import integrated,zero_channels
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True)
    original_constraint=c.parentConstraint;original_zero=zero_channels.build
    remove=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))['remove']
    rows=[]
    try:
        c.autoKeyframe(state=False)
        for invalid in (0,-1,float('nan'),float('inf'),True,'0.001',1e-9):
            try:integrated.build({},pose_tolerance=invalid)
            except ValueError as exc:assert '核对容差' in str(exc)
            else:raise AssertionError('Invalid tolerance accepted: '+repr(invalid))
        assert set(c.ls(long=True))==before
        for stage,tolerance,offset in (('normal',None,.0002),('assembly',None,.0002),('assembly',.001,.0002),('zero',None,.0002),('zero',.001,.0002),('assembly',1,1.0434503756331615),('assembly',2,1.0434503756331615),('zero',2,1.0434503756331615),('normal',1e100,.0002)):
            prefix='_poseTolerance_'+uuid.uuid4().hex[:7];rig=None
            target=c.createNode('transform',name=prefix+'_target')
            for f,v in ((0,10),(1,11)):c.setKeyframe(target,at='translateX',t=f,v=v)
            c.currentTime(0)
            edge=c.connectionInfo(target+'.translateX',sfd=True)
            curve=edge.split('.')[0];keys=(c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))
            fixture=set(c.ls(long=True));constraint_name=prefix+':shoulder_R_target1'
            def perturb():c.setAttr(constraint_name+'.target[0].targetOffsetTranslateX',offset)
            def constrained(*args,**kwargs):
                result=original_constraint(*args,**kwargs)
                if stage=='assembly' and kwargs.get('name')==constraint_name:perturb()
                return result
            def zeroed(*args,**kwargs):
                result=original_zero(*args,**kwargs)
                if stage=='zero':perturb()
                return result
            c.parentConstraint=constrained;zero_channels.build=zeroed
            kwargs={} if tolerance is None else dict(pose_tolerance=tolerance)
            expected_pass=stage=='normal' or (tolerance is not None and tolerance>=offset)
            try:
                try:
                    rig=integrated.build({'shoulder_R':dict(targets=[target],copy_animation=True,start_frame=0,end_frame=1)},
                                         namespace=prefix,zero_controls=True,**kwargs)
                except RuntimeError as exc:
                    assert not expected_pass,str(exc)
                    assert ('动画/姿态核对失败' if stage=='assembly' else '零位控制器未保留动画') in str(exc),str(exc)
                    assert '容差' in str(exc)
                    assert set(c.ls(long=True))==fixture,dict(added=list(set(c.ls(long=True))-fixture),missing=list(fixture-set(c.ls(long=True))))
                    assert c.connectionInfo(target+'.translateX',sfd=True)==edge
                    assert (c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))==keys
                    assert abs(c.getAttr(target+'.translateX')-10)<1e-8
                    rows.append(dict(stage=stage,rejected=True,rollback=True))
                else:
                    assert expected_pass
                    stored=json.loads(c.getAttr(rig['root']+'.integratedRigData'))
                    assert stored['pose_tolerance']==(1e-4 if tolerance is None else tolerance)
                    if stage!='normal':assert abs(stored['max_world_error']-offset)<1e-8
                    rows.append(dict(stage=stage,accepted=True,tolerance=stored['pose_tolerance'],error=stored['max_world_error']))
            finally:
                c.parentConstraint=original_constraint;zero_channels.build=original_zero
                if rig:remove(rig)
                for n in sorted(set(c.ls(long=True))-before,key=lambda x:x.count('|'),reverse=True):
                    if c.objExists(n):c.delete(n)
        return dict(passed=True,invalid_values_rejected=7,cases=rows)
    finally:
        c.parentConstraint=original_constraint;zero_channels.build=original_zero
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(long=True))==before
