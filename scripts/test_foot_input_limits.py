"""Independent Maya regression for authored foot bounds and rotation routing."""
def run(out):
    import maya.cmds as c, maya.api.OpenMaya as om, maya.mel as mel, maya.utils
    import json
    from maya_agent.rigs import live_edit,live_arm_manual,scene_data,foot_space,foot_translation
    c.file(str(out/'character.ma'),open=True,force=True,executeScriptNodes=False)
    maya.utils.processIdleEvents()
    from PySide2 import QtCore
    loop=QtCore.QEventLoop();QtCore.QTimer.singleShot(250,loop.quit);loop.exec_()
    rig=json.loads((out/'rig.json').read_text(encoding='utf-8'))
    joints=[j for p in rig['parts'].values() for j in p.get('joints',[])]
    def poses():return {j:c.xform(j,q=True,ws=True,m=True) for j in joints}
    def error(before):return max(abs(a-b) for j,m in before.items() for a,b in zip(m,c.xform(j,q=True,ws=True,m=True)))
    def drag(handles,delta,rotate=False):
        c.setToolTo('RotateSuperContext' if rotate else 'moveSuperContext');c.select(handles,r=True)
        live_edit.before_drag('foot-input-test')
        for e in live_edit._gesture['arm_gestures']:
            live_arm_manual.prepare_native_sample(e,suspend=False)
            if rotate:c.setAttr(e['proxy']+'.rx',30)
            else:
                move=delta*e['parent'].inverse()
                for a,start,dv in zip('XYZ',e['native_start'],move):c.setAttr(e['proxy']+'.translate'+a,start+dv)
        live_edit.update_drag(force=True)
    c.currentTime(1);c.autoKeyframe(state=False);cases=0;max_error=0
    for side in ('leg_L','leg_R'):
        p=rig['parts'][side];controls=p['zero_controls'];foot=controls['foot']
        d=scene_data.read(p['root']+'.liveAlignmentData');ns=p['namespace']
        for mode in (0,1):
            foot_space.switch(p['root'],mode,key=False)
            for role in ('heel','toe_end','ball'):
                # Rotate another pivot first: this exposed the missed TR path.
                other='toe_end' if role=='heel' else 'heel'
                c.setAttr(controls[other]+'.rx',32)
                original_foot=c.getAttr(foot+'.translate')[0]
                # A reachable ball pivot often needs no TR compensation. Start
                # outside reach to exercise a nonzero compensation explicitly.
                if role=='ball':
                    c.setKeyframe(foot,at='tx',time=1,value=original_foot[0]+40)
                    c.setAttr(foot+'.tx',original_foot[0]+40)
                own=c.getAttr(controls[role]+'.t')[0];before=poses()
                transfer=foot_translation.transfer_rotation
                try:
                    foot_translation.transfer_rotation=lambda entry:None
                    drag([controls[role]],None,rotate=True)
                    expected=poses();toe_expected=c.xform(controls['toe'],q=True,ws=True,m=True)
                    compensation=c.getAttr(live_edit._gesture['arm_gestures'][0]['source']+'.translate')[0]
                    live_edit.after_drag('foot-input-test');c.undo()
                finally:foot_translation.transfer_rotation=transfer
                drag([controls[role]],None,rotate=True)
                held=poses();entry=live_edit._gesture['arm_gestures'][0]
                assert error(expected)<1e-5,('rotation pose changed',side,mode,role,error(expected))
                assert max(abs(a-b) for a,b in zip(toe_expected,c.xform(controls['toe'],q=True,ws=True,m=True)))<1e-5,('toe display',side,mode,role)
                if role=='ball':assert max(abs(a-b) for a,b in zip(compensation,own))>1e-4,'ball case did not exercise translation'
                assert max(abs(a-b) for a,b in zip(c.getAttr(entry['source']+'.t')[0],own))<1e-8
                live_edit.after_drag('foot-input-test')
                assert max(abs(a-b) for a,b in zip(c.getAttr(controls[role]+'.t')[0],own))<1e-8
                assert error(held)<1e-5
                # Native S must key the ankle companion as well as the pivot.
                keyed_values={n+'.'+a:c.getAttr(n+'.'+a) for n in controls.values() for a in live_edit.TR}
                mel.eval(c.runTimeCommand('SetKey',q=True,command=True))
                c.undoInfo(stateWithoutFlush=False)
                try:c.currentTime(1.25);c.currentTime(1)
                finally:c.undoInfo(stateWithoutFlush=True)
                if error(held)>=1e-5:
                    (out/'ball-key-debug.json').write_text(json.dumps({p:dict(before=v,after=c.getAttr(p),keys=c.keyframe(p,q=True,vc=True),times=c.keyframe(p,q=True,tc=True)) for p,v in keyed_values.items() if abs(c.getAttr(p)-v)>1e-8},indent=2),encoding='utf-8')
                assert error(held)<1e-5,('key replay',side,mode,role,error(held))
                c.undo();c.undo();assert error(before)<1e-5,('rotation undo',error(before))
                c.setAttr(controls[other]+'.rx',0);cases+=1
                if role=='ball':
                    c.setKeyframe(foot,at='tx',time=1,value=original_foot[0])
                    c.setAttr(foot+'.translate',*original_foot)
            for roles in (('foot',),('heel',),('toe_end',),('ball',),('heel','toe_end','ball'),('foot','ball')):
                before=poses();own={r:c.getAttr(controls[r]+'.t')[0] for r in ('heel','toe_end')}
                delta=om.MVector(0,-100,0)
                drag([controls[r] for r in roles],delta)
                entries=live_edit._gesture['arm_gestures'];route=entries[0]['foot_move']
                assert route.get('clamped'),(side,mode,roles)
                length,limit=route['reach']
                assert c.getAttr(length+'.tx')-c.getAttr(limit+'.tx')<1e-5
                # Further radial overshoot cannot accumulate on source or UI.
                base=om.MVector(*c.xform(c.listRelatives(length,p=True,f=True)[0],q=True,ws=True,t=True))
                target=om.MVector(*list(live_edit._frame(d['targets']['foot']))[12:15])
                outward=(target-base).normal()
                saved=c.getAttr(route['source']+'.t')[0];native=c.getAttr(entries[0]['proxy']+'.t')[0]
                for multiple in (100,1000,10000):
                    for e in entries:
                        live_arm_manual.prepare_native_sample(e,suspend=False)
                        accepted=om.MVector(*list(live_edit._frame(route['source']))[12:15])-om.MVector(*route['position'])
                        move=(accepted+outward*multiple)*e['parent'].inverse()
                        for a,start,dv in zip('XYZ',e['native_start'],move):c.setAttr(e['proxy']+'.translate'+a,start+dv)
                    live_edit.update_drag(force=True)
                    err=max(abs(a-b) for a,b in zip(saved,c.getAttr(route['source']+'.t')[0]));max_error=max(err,max_error)
                    assert err<1e-5,('input grows',side,mode,roles,err)
                    assert max(abs(a-b) for a,b in zip(native,c.getAttr(entries[0]['proxy']+'.t')[0]))<1e-5
                held=poses();live_edit.after_drag('foot-input-test');assert error(held)<1e-5
                for r,v in own.items():assert max(abs(a-b) for a,b in zip(v,c.getAttr(controls[r]+'.t')[0]))<1e-8
                c.undo();assert error(before)<1e-5
                c.redo();assert error(held)<1e-5;c.undo();cases+=1
    # Authored old roll keys remain untouched; clipping follows scale/stretch
    # from the original solver rather than a hard-coded world-space radius.
    p=rig['parts']['leg_L'];controls=p['zero_controls'];ns=p['namespace']
    settings=ns+':strech_ik_foot1_L1';master=rig['master_control']
    scales=(.5,2) if c.objExists(master+'.overallScale') else (1,)
    for scale in scales:
        if c.objExists(master+'.overallScale'):c.setAttr(master+'.overallScale',scale)
        for stretch in (0,.5):
            c.setAttr(settings+'.lenght_coeff',stretch)
            for role in ('heel','toe_end'):c.setAttr(controls[role]+'.rx',23)
            before=poses();drag([controls['toe_end']],om.MVector(100,-200,50))
            route=live_edit._gesture['arm_gestures'][0]['foot_move'];length,limit=route['reach']
            assert route['clamped'] and abs(c.getAttr(length+'.tx')-c.getAttr(limit+'.tx'))<1e-5
            held=poses();live_edit.after_drag('foot-input-test');assert error(held)<1e-5
            c.undo();assert error(before)<1e-5;cases+=1
    return dict(passed=True,cases=cases,max_error=max_error,rotation_routes_translation=True,native_S=True,undo_redo=True,overshoot_channels_bounded=True,scales=scales,stretch=True)
