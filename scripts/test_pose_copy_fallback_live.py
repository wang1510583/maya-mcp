"""Optional continuous-rotation fallback must preserve baked poses, not errors."""
import json
import runpy
import uuid
from pathlib import Path
import maya.cmds as c


def verify():
    from maya_agent.rigs import integrated
    from maya_agent.rigs.integrated import master_control
    from maya_agent.rigs.custom_body import continuous_rotation as continuous
    remove=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))['remove']
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True)
    old_candidate=continuous.candidate;old_master=master_control.attach
    results=[]
    try:
        c.autoKeyframe(state=False)
        for case in ('normal','fallback','unexpected_error','static','bad_final_pose'):
            prefix='_poseCopy_'+uuid.uuid4().hex[:7];rig=None;targets=[]
            for i in range(3):
                n=c.createNode('transform',name=prefix+'_source'+str(i));targets.append(n)
                c.setAttr(n+'.translateY',10+i*3)
                if case!='static':
                    for f in (0,1,2):c.setKeyframe(n,at='translateX',t=f,v=f*.1)
            expected={}
            for f in (0,1,2):
                c.currentTime(f);expected[f]={n:c.xform(n,q=True,ws=True,m=True) for n in targets}
            c.currentTime(0);fixture=set(c.ls(long=True))
            edges={n+'.'+a:c.connectionInfo(n+'.'+a,sfd=True) for n in targets for a in ('tx','ty','tz','rx','ry','rz')}
            def candidate(*args,**kwargs):
                if case=='unexpected_error':raise RuntimeError('injected unexpected build error')
                data=old_candidate(*args,**kwargs)
                if case!='normal':
                    # Cause a genuine measured candidate mismatch. enable()
                    # must clean it, then integrated may retain the old graph.
                    n=c.createNode('composeMatrix',name=prefix+':badCandidate')
                    c.setAttr(n+'.inputRotateX',160);data['created'].append(n)
                    data['outputs'][0]['replacement']=n+'.inputRotate'
                return data
            def master(*args,**kwargs):
                value=old_master(*args,**kwargs)
                if case=='bad_final_pose':c.setAttr(prefix+':body_target1.target[0].targetOffsetTranslateX',.02)
                return value
            continuous.candidate=candidate;master_control.attach=master
            try:
                try:
                    rig=integrated.build({'body':dict(targets=targets,copy_animation=case!='static',start_frame=0,end_frame=2)},namespace=prefix,zero_controls=True)
                except Exception as exc:
                    assert case in ('unexpected_error','static','bad_final_pose'),str(exc)
                    if case=='unexpected_error':assert 'injected unexpected' in str(exc)
                    if case=='static':assert isinstance(exc,continuous.PoseMismatchError)
                    if case=='bad_final_pose':assert '最终动画核对失败' in str(exc)
                    assert set(c.ls(long=True))==fixture,(case,set(c.ls(long=True))-fixture)
                    assert all(c.connectionInfo(p,sfd=True)==e for p,e in edges.items())
                    results.append(dict(case=case,rejected=True,rollback=True))
                else:
                    assert case in ('normal','fallback')
                    assert bool(rig.get('continuous_rotation_fallback'))==(case=='fallback')
                    if case=='fallback':assert not c.objExists(rig['parts']['body']['controls']['hips']+'.'+continuous.ATTRIBUTE)
                    error=0.
                    for f,poses in expected.items():
                        c.currentTime(f)
                        for n,m in poses.items():error=max(error,max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
                    assert error<1e-4,error
                    results.append(dict(case=case,accepted=True,error=error))
            finally:
                continuous.candidate=old_candidate;master_control.attach=old_master
                if rig:remove(rig)
                for n in sorted(set(c.ls(long=True))-before,key=lambda x:x.count('|'),reverse=True):
                    if c.objExists(n):c.delete(n)
        return dict(passed=True,cases=results)
    finally:
        continuous.candidate=old_candidate;master_control.attach=old_master
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(long=True))==before
