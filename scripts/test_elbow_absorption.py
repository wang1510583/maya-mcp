"""FK elbow edits canonicalize into the existing arm inputs in a disposable Maya."""
def run(out):
    import json, hashlib
    import maya.cmds as c, maya.mel as mel, maya.utils
    from maya_agent.rigs import scene_data,live_edit,arm_ik,live_arm_manual
    import rig_runtime_assistant as assistant
    fixture=out/'elbow-transfer-source.mb'
    digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
    cases=[]
    for layer_mode in (None,'native','auto'):
        c.file(new=True,force=True)
        for ns in ('actorA','actorB'):c.file(str(fixture),reference=True,namespace=ns,executeScriptNodes=False)
        maya.utils.processIdleEvents();assistant.enable();c.autoKeyframe(state=False)
        rigs=[scene_data.read(ns+':customCharacter_02:character_rig.integratedRigData') for ns in ('actorA','actorB')]
        def pose(rig):return {n:c.xform(n,q=True,ws=True,m=True) for p in rig['parts'].values() for n in p.get('joints',[])}
        def error(wanted):return max(abs(a-b) for n,m in wanted.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        source_keys={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve') if c.referenceQuery(n,isNodeReferenced=True)}
        frame=20
        for side in ('arm_L','arm_R'):
            p=rigs[0]['parts'][side];controls=p['zero_controls'];pole=controls['pole_locator']
            for auto in ((False,True) if layer_mode is None else (layer_mode=='auto',)):
                for mode in (0,1):
                    frame+=3;c.currentTime(frame);c.autoKeyframe(state=False);arm_ik.switch(p['root'],mode,key=True)
                    layer=None
                    if layer_mode:
                        for n in c.ls(type='animLayer') or []:c.animLayer(n,e=True,selected=False,preferred=False)
                        layer=c.animLayer('elbowEditLayer#',weight=.5,selected=True,preferred=True)
                        c.animLayer(layer,e=True,attribute=[pole+'.translate'+a for a in 'XYZ'])
                    # Baseline keys make the Auto Key test meaningful.
                    editable=[n+'.'+a for n in controls.values() for a in live_edit.TR if not c.getAttr(n+'.'+a,lock=True)]
                    c.setKeyframe(editable)
                    for chosen in ([pole],[pole,controls['middle_fk']]):
                        c.select(chosen,r=True);mel.eval(c.runTimeCommand('MoveTool',q=True,command=True));maya.utils.processIdleEvents()
                        before=pose(rigs[0]);other=pose(rigs[1]);keys_before={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
                        ik=arm_ik._data(p['root'])
                        debug_plugs=editable+[n+'.'+a for n in ik['controls'].values() for a in live_edit.TR]+ik['offset_attrs']
                        debug_before={v:c.getAttr(v) for v in debug_plugs}
                        c.autoKeyframe(state=auto);live_edit.before_drag('elbow-click');gesture=live_edit._gesture;live_edit.after_drag('elbow-click')
                        if error(before)>=1e-5:
                            diffs={v:[old,c.getAttr(v)] for v,old in debug_before.items() if abs(c.getAttr(v)-old)>1e-10}
                            (out/'elbow-noop-debug.json').write_text(json.dumps(dict(diffs=diffs,entries=[dict(role=e['role'],changed=e['changed'],snapshot=e['snapshot'][0]) for e in gesture['arm_gestures']],native=gesture.get('native_plugs')),indent=2),encoding='utf-8')
                        assert error(before)<1e-5,('no-op pose',side,mode,auto,layer_mode,chosen,error(before),len(cases))
                        assert all((c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==v for n,v in keys_before.items()),'no-op keys'
                        live_edit.before_drag('elbow-move')
                        for n in chosen:c.setAttr(n+'.translateZ',c.getAttr(n+'.translateZ')+.7)
                        live_edit.update_drag(force=True);held=pose(rigs[0]);live_edit.after_drag('elbow-move')
                        assert error(held)<1e-5,('release',side,mode,layer_mode,error(held))
                        if not mode:assert abs(c.getAttr(pole+'.translateZ'))<1e-7,('residual Z',side,c.getAttr(pole+'.translateZ'))
                        c.undo();assert error(before)<1e-5,('undo',side,mode,error(before))
                        c.redo();assert error(held)<1e-5,('redo',side,mode,error(held))
                        if not auto:mel.eval(c.runTimeCommand('SetKey',q=True,command=True))
                        keyed_values={v:c.getAttr(v) for v in debug_plugs+[ik['global_plug']]}
                        c.currentTime(frame+1);c.currentTime(frame);maya.utils.processIdleEvents()
                        if error(held)>=1e-5:
                            (out/'elbow-replay-debug.json').write_text(json.dumps({v:[old,c.getAttr(v),c.keyframe(v,q=True,time=(frame,frame),vc=True)] for v,old in keyed_values.items() if abs(c.getAttr(v)-old)>1e-10},indent=2),encoding='utf-8')
                        assert error(held)<1e-5,('replay',side,mode,auto,layer_mode,chosen,error(held),len(cases))
                        assert error(other)<1e-5,'other reference changed'
                        cases.append(dict(side=side,mode=mode,auto=auto,layer=bool(layer),multi=len(chosen)>1))
        assert all((c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==v for n,v in source_keys.items()),'reference curves changed'
        saved=out/('elbow-roundtrip-'+str(layer_mode)+'.ma')
        expected=pose(rigs[0]);c.file(rename=str(saved));c.file(save=True,type='mayaAscii',force=True)
        c.file(str(saved),open=True,force=True,executeScriptNodes=False);maya.utils.processIdleEvents()
        assert error(expected)<1e-5,'save/reopen pose'
    assert hashlib.sha256(fixture.read_bytes()).hexdigest()==digest
    # Replay the user's captured 7.70-Z pose without opening their live scene.
    captured=json.loads((out/'elbow-current-inputs.json').read_text(encoding='utf-8'))
    c.file(str(fixture),open=True,force=True,executeScriptNodes=False)
    maya.utils.processIdleEvents();assistant.enable();c.autoKeyframe(state=False);c.currentTime(0)
    for p,v in captured['channels'].items():c.setAttr(p,v)
    c.setKeyframe(list(captured['channels']))
    rig=scene_data.read('customCharacter_02:character_rig.integratedRigData')
    part=rig['parts']['arm_L'];control=part['zero_controls']['middle_fk'];pole=part['zero_controls']['pole_locator']
    c.select(control,r=True);mel.eval(c.runTimeCommand('MoveTool',q=True,command=True));maya.utils.processIdleEvents()
    live_edit.before_drag('reported-pose');c.setAttr(control+'.translateZ',c.getAttr(control+'.translateZ')+.2)
    live_edit.update_drag(force=True);expected=pose(rig);live_edit.after_drag('reported-pose')
    assert error(expected)<1e-5,'reported release pose'
    assert abs(c.getAttr(pole+'.translateZ'))<1e-7,'reported residual Z'
    mel.eval(c.runTimeCommand('SetKey',q=True,command=True));c.currentTime(1);c.currentTime(0)
    assert error(expected)<1e-5,'reported pose replay'
    return dict(passed=True,cases=len(cases),references=2,source_unchanged=True,native_S=True,auto_key=True,half_weight_layer=True,undo_redo=True,save_reopen=True)
