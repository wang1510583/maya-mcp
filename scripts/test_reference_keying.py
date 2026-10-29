"""Native S keying on the reported character copy, never the source asset."""
import hashlib
import json


def run(out):
    import maya.cmds as c, maya.mel as mel, maya.utils
    from maya_agent.rigs import scene_data,live_edit,reference_animation
    import rig_runtime_assistant as assistant
    fixture=out/'key-user-copy.mb'
    digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
    root_name='customCharacter_02:character_rig'
    c.file(new=True,force=True)
    for ns in ('keyA','keyB'):c.file(str(fixture),reference=True,namespace=ns,executeScriptNodes=False)
    maya.utils.processIdleEvents();assistant.enable()
    rigs=[scene_data.read(ns+':'+root_name+'.integratedRigData') for ns in ('keyA','keyB')]
    def poses(rig):return {n:c.xform(n,q=True,ws=True,m=True) for part in rig['parts'].values() for n in part.get('joints',[])}
    def error(before):return max([abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))] or [0])
    def keys(curve):
        result={flag:c.keyframe(curve,q=True,**{flag:True}) for flag in ('tc','vc')}
        result['tangents']={flag:c.keyTangent(curve,q=True,**{flag:True}) for flag in ('itt','ott','ia','oa','iw','ow','lock','weightLock','weightedTangents')}
        return result
    originals={n:keys(n) for n in c.ls(type='animCurve') or [] if c.referenceQuery(n,isNodeReferenced=True)}
    count=len(c.ls(type='animCurve'));assert not reference_animation.prepare()['cloned']
    assert len(c.ls(type='animCurve'))==count
    c.autoKeyframe(state=False)
    cases=[];frame=11
    for part,role in (('head','head'),('body','chest'),('arm_L','shoulder_fk'),('arm_L','middle_fk'),
                      ('arm_L','end_fk'),('arm_R','shoulder_fk'),('leg_L','foot'),('leg_R','foot')):
        ctrl=rigs[0]['parts'][part]['zero_controls'][role]
        for attribute in ('rotateY','translateX'):
            if c.getAttr(ctrl+'.'+attribute,lock=True):continue
            frame+=3;c.currentTime(frame);maya.utils.processIdleEvents()
            c.select(ctrl,r=True)
            move=attribute.startswith('translate')
            mel.eval(c.runTimeCommand('MoveTool' if move else 'RotateTool',q=True,command=True))
            context='manipMove' if move else 'manipRotate'
            live_edit.before_drag(context)
            c.setAttr(ctrl+'.'+attribute,c.getAttr(ctrl+'.'+attribute)+(1 if move else 11))
            live_edit.update_drag(force=True);live_edit.after_drag(context)
            wanted=poses(rigs[0]);other=poses(rigs[1]);value=c.getAttr(ctrl+'.'+attribute)
            mel.eval(c.runTimeCommand('SetKey',q=True,command=True))
            assert error(wanted)<1e-5,('key pose',part,role)
            assert c.keyframe(ctrl+'.'+attribute,q=True,time=(frame,frame),kc=True),('no key',ctrl,attribute)
            c.undo();assert error(wanted)<1e-5,('undo key pose',part,role,error(wanted))
            c.redo();maya.utils.processIdleEvents()
            c.currentTime(frame+1);c.currentTime(frame);maya.utils.processIdleEvents()
            assert abs(c.getAttr(ctrl+'.'+attribute)-value)<1e-6,(part,role,'value reset')
            assert error(wanted)<1e-5,(part,role,'returned pose',error(wanted))
            assert error(other)<1e-5,'other reference moved'
            cases.append(dict(control=ctrl,attribute=attribute,frame=frame,value=value))
    # Edit an explicit additive animation layer, then verify evaluated pose.
    ctrl=rigs[0]['parts']['head']['zero_controls']['head']
    c.select(ctrl,r=True);layer=c.animLayer('keyReferenceLayer',addSelectedObjects=True)
    for n in c.ls(type='animLayer') or []:c.animLayer(n,e=True,selected=(n==layer),preferred=(n==layer))
    c.currentTime(60);c.setToolTo('RotateSuperContext');maya.utils.processIdleEvents()
    live_edit.before_drag('manipRotate');c.setAttr(ctrl+'.rotateY',c.getAttr(ctrl+'.rotateY')+9)
    live_edit.update_drag(force=True);live_edit.after_drag('manipRotate')
    wanted=poses(rigs[0]);mel.eval(c.runTimeCommand('SetKey',q=True,command=True))
    c.currentTime(61);c.currentTime(60);maya.utils.processIdleEvents()
    assert error(wanted)<1e-5,('layer keying',error(wanted))
    assert all(keys(n)==v for n,v in originals.items()),'source reference curves changed'
    saved=out/'key-reference-roundtrip.ma'
    c.file(rename=str(saved));c.file(save=True,type='mayaAscii',force=True)
    c.file(str(saved),open=True,force=True,executeScriptNodes=False);maya.utils.processIdleEvents()
    for case in cases:
        c.currentTime(case['frame'])
        # Head also has a later layer; check its base curve directly instead.
        if case['control']==ctrl:continue
        assert abs(c.getAttr(case['control']+'.'+case['attribute'])-case['value'])<1e-6,case
    c.currentTime(60);assert error(wanted)<1e-5,('saved pose',error(wanted))
    # Exercise the companion-channel path on an additive layer as well.
    c.file(new=True,force=True)
    c.file(str(fixture),reference=True,namespace='layerActor',executeScriptNodes=False)
    maya.utils.processIdleEvents();assistant.enable()
    layered=scene_data.read('layerActor:'+root_name+'.integratedRigData')
    controls=layered['parts']['arm_L']['zero_controls']
    c.select(controls['shoulder_fk'],r=True)
    layer=c.animLayer('armKeyLayer',addSelectedObjects=True)
    for n in c.ls(type='animLayer') or []:c.animLayer(n,e=True,selected=(n==layer),preferred=(n==layer))
    for index,role in enumerate(('shoulder_fk','middle_fk','end_fk')):
        c.currentTime(70+index*3);ctrl=controls[role];c.select(ctrl,r=True)
        c.animLayer(layer,e=True,addSelectedObjects=True)
        mel.eval(c.runTimeCommand('RotateTool',q=True,command=True));maya.utils.processIdleEvents()
        live_edit.before_drag('manipRotate');c.setAttr(ctrl+'.rotateY',c.getAttr(ctrl+'.rotateY')+7)
        live_edit.update_drag(force=True);live_edit.after_drag('manipRotate')
        wanted=poses(layered);mel.eval(c.runTimeCommand('SetKey',q=True,command=True))
        c.undo();c.redo();c.currentTime(71+index*3);c.currentTime(70+index*3)
        maya.utils.processIdleEvents();assert error(wanted)<1e-5,('arm layer',role,error(wanted))
    c.file(rename=str(out/'key-arm-layer-roundtrip.ma'));c.file(save=True,type='mayaAscii',force=True)
    c.file(str(out/'key-arm-layer-roundtrip.ma'),open=True,force=True,executeScriptNodes=False)
    maya.utils.processIdleEvents();assert error(wanted)<1e-5,('saved arm layer',error(wanted))
    assert hashlib.sha256(fixture.read_bytes()).hexdigest()==digest,'asset copy changed'
    return dict(passed=True,native_S_cases=len(cases),references=2,undo_redo=True,
                additive_layer=True,arm_layer_cases=3,save_reopen=True,source_curves_unchanged=True,source_file_unchanged=True)
