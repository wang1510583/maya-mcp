"""Compare roll-handle reach with the solved ankle in an isolated Maya."""
def run(out):
    import json,hashlib
    import maya.cmds as c,maya.mel as mel,maya.utils
    import maya.api.OpenMaya as om
    import rig_runtime_assistant as assistant
    from maya_agent.rigs import live_edit,live_arm_manual,foot_reach,scene_data,foot_space
    fixture=out/'elbow-transfer-source.mb';digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
    assistant.disable();c.file(new=True,force=True)
    for ns in ('footA','shotFootB'):c.file(str(fixture),reference=True,namespace=ns,executeScriptNodes=False)
    rigs=[scene_data.read(ns+':customCharacter_02:character_rig.integratedRigData') for ns in ('footA','shotFootB')]
    joints=[n for rig in rigs for p in rig['parts'].values() for n in p.get('joints',[])]
    def poses():return {n:c.xform(n,q=True,ws=True,m=True) for n in joints}
    def error(before):return max(abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
    def curves():return {n:[c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)] for n in c.ls(type='animCurve')}
    before=poses();keys=curves();cycle_before=set(c.cycleCheck(all=True,list=True) or [])
    created=foot_reach.install();assert created and error(before)<1e-8 and curves()==keys
    assert not foot_reach.install(),'duplicate installation'
    assert set(c.cycleCheck(all=True,list=True) or [])==cycle_before,'new cycle'
    assistant.enable();c.autoKeyframe(state=False)
    cases=0;max_error=0
    for rig in rigs:
        for side in ('leg_L','leg_R'):
            p=rig['parts'][side];d=scene_data.read(p['root']+'.liveAlignmentData')
            controls=p['zero_controls'];foot=controls['foot'];source=d['inputs']['foot']
            def check():
                nonlocal max_error,cases
                delta=om.MVector(*c.xform(d['position_targets']['foot'],q=True,ws=True,t=True))-om.MVector(*list(live_edit._frame(d['targets']['foot']))[12:15])
                for role in ('heel','toe_end','ball','toe'):
                    choice=foot_reach._choice(d['controls'][role])
                    compensation=c.connectionInfo(choice+'.input[1]',sfd=True).split('.')[0]
                    raw=om.MMatrix(c.getAttr(compensation+'.matrixIn[0]'))
                    expected=list(raw)
                    for i in range(3):expected[12+i]+=delta[i]
                    actual=c.xform(controls[role],q=True,ws=True,m=True)
                    err=max(abs(a-b) for a,b in zip(expected,actual));max_error=max(max_error,err)
                    assert err<1e-5,(side,role,err)
                foot_pos=om.MVector(*c.xform(foot,q=True,ws=True,t=True))
                assert (foot_pos-om.MVector(*c.xform(d['position_targets']['foot'],q=True,ws=True,t=True))).length()<1e-5
                cases+=1
            original={n+'.'+a:c.getAttr(n+'.'+a) for n in controls.values() for a in live_edit.TR if not c.getAttr(n+'.'+a,lock=True)}
            for mode in (0,1):
                foot_space.switch(p['root'],mode,key=False)
                for distance in (0,.1,60,400,-200,0):
                    movement=om.MVector(distance,-distance*.5,distance*.2)*om.MMatrix(c.getAttr(source+'.parentMatrix[0]')).inverse()
                    for axis,value in zip('XYZ',movement):c.setAttr(foot+'.translate'+axis,original[foot+'.translate'+axis]+value)
                    check()
                for role in ('heel','toe_end','ball'):
                    c.setAttr(controls[role]+'.rotateX',23);check();c.setAttr(controls[role]+'.rotateX',original[controls[role]+'.rotateX'])
                for roles in (('heel',),('toe_end',),('ball',),('heel','toe_end','ball'),('foot','heel')):
                    c.select([controls[r] for r in roles],r=True);mel.eval(c.runTimeCommand('MoveTool',q=True,command=True))
                    base=poses();roll_values={r:c.getAttr(controls[r]+'.translate')[0] for r in ('heel','toe_end','ball')}
                    live_edit.before_drag('reach-test')
                    for e in live_edit._gesture['arm_gestures']:
                        live_arm_manual.prepare_native_sample(e,suspend=False)
                        move=om.MVector(300,-200,100)*e['parent'].inverse()
                        for a,start,value in zip('XYZ',e['native_start'],move):c.setAttr(e['proxy']+'.translate'+a,start+value)
                    live_edit.update_drag(force=True);held=poses();check();live_edit.after_drag('reach-test')
                    assert error(held)<1e-5;check()
                    assert all(c.getAttr(controls[r]+'.translate')[0]==v for r,v in roll_values.items())
                    c.undo();assert error(base)<1e-5
                    c.redo();assert error(held)<1e-5;c.undo()
            for plug,value in original.items():c.setAttr(plug,value)
    expected=poses();saved=out/'foot-reach-roundtrip.ma'
    c.file(rename=str(saved));c.file(save=True,type='mayaAscii',force=True)
    c.file(str(saved),open=True,force=True,executeScriptNodes=False);maya.utils.processIdleEvents()
    assert error(expected)<1e-5 and not foot_reach.install()
    root=rigs[0]['parts']['leg_L']['root'];before=poses();keys=curves()
    removed=foot_reach.remove(root);assert removed and all(not c.objExists(n) for n in removed)
    assert error(before)<1e-8 and curves()==keys
    assert foot_reach.ensure(root) and not foot_reach.ensure(root)
    assert hashlib.sha256(fixture.read_bytes()).hexdigest()==digest
    return dict(passed=True,cases=cases,max_error=max_error,reference_count=2,install_preserves_pose_and_keys=True,no_cycles=True,idempotent=True,undo_redo=True,save_reopen=True,remove_reinstall=True)
