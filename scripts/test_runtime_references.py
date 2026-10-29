"""Real Maya GUI regression: original rig plus two references of the same file."""
import json
from pathlib import Path


def run(out):
    import maya.cmds as c
    import maya.utils
    import maya.api.OpenMaya as om
    from maya_agent.rigs import scene_data, live_edit, arm_ik, live_arm_manual, external_constraints
    import rig_runtime_assistant as assistant
    original=json.loads((out/'rig.json').read_text(encoding='utf-8'))
    messages=[]
    callback=om.MCommandMessage.addCommandOutputCallback(lambda message,kind,*_: messages.append(message)
                                                        if kind in (om.MCommandMessage.kWarning,om.MCommandMessage.kError) else None)
    fixture=str(out/'character.ma')
    c.file(fixture,open=True,force=True,executeScriptNodes=False)
    # The local copy is a different shot, not a reference back into itself.
    c.file(rename=str(out/'reference-test-working.ma'))
    roots=[original['root']]
    refs=[]
    for ns in ('actorA','shot:actorB'):
        if ':' in ns and not c.namespace(exists=ns.rsplit(':',1)[0]):
            c.namespace(add=ns.rsplit(':',1)[0])
        c.file(fixture,reference=True,namespace=ns,mergeNamespacesOnClash=False,executeScriptNodes=False)
        roots.append(ns+':'+original['root'])
        assert c.objExists(roots[-1]),(ns,c.ls('::character_rig',long=True))
        refs.append(c.referenceQuery(roots[-1],referenceNode=True))
    maya.utils.processIdleEvents();assistant.enable()
    rigs=[scene_data.read(root+'.integratedRigData') for root in roots]
    def nodes(rig):
        return list(dict.fromkeys(n for part in rig['parts'].values() for n in part.get('joints',[])))
    def pose(rig):return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes(rig)}
    def delta(before):return max([abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))] or [0])
    def curves():
        return {n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve') or []}
    texts={n+'.'+a:c.getAttr(n+'.'+a) for n in c.ls(type='transform',long=True) or []
           for a in ('integratedRigData','zeroChannelData','liveAlignmentData') if c.attributeQuery(a,node=n,exists=True)}
    original_curves=curves()
    cases=[];mode_cases=[]
    c.currentTime(1);c.autoKeyframe(state=False);c.setToolTo('RotateSuperContext')
    maya.utils.processIdleEvents()
    for index,rig in enumerate(rigs[1:],1):
        other=[pose(r) for j,r in enumerate(rigs) if j!=index]
        for key,part in rig['parts'].items():
            for role,control in part.get('zero_controls',{}).items():
                attrs=[a for a in ('rotateX','rotateY','rotateZ','translateX','translateY','translateZ')
                       if c.objExists(control+'.'+a) and not c.getAttr(control+'.'+a,lock=True)]
                if not attrs:continue
                # Exercise the same entry/commit path used by the viewport.
                for attr in attrs[:3]:
                    c.select(control,r=True)
                    before=pose(rig)
                    try:
                        live_edit.before_drag('manipRotate')
                        assert live_edit._gesture,(key,role,'gesture not started')
                        c.setAttr(control+'.'+attr,c.getAttr(control+'.'+attr)+3)
                        live_edit.update_drag(force=True)
                    finally:
                        if live_edit._gesture:live_edit.after_drag('manipRotate')
                    c.undo();maya.utils.processIdleEvents()
                    assert delta(before)<2e-5,(key,role,attr,'undo pose',delta(before))
                    assert all(delta(p)<2e-5 for p in other),(key,role,'other character moved')
                    cases.append((index,key,role,attr))
        # Every registered space family must match without moving another rig.
        owners=[n for n in c.ls('::*.armWorldIKData','::*.footSpaceData','::*.upperArmSpaceData',
                             '::*.matchedSpaceData','::*.bodyDriveData','::*.chestSpaceData',objectsOnly=True) or []
                if c.referenceQuery(n,isNodeReferenced=True) and c.referenceQuery(n,referenceNode=True)==refs[index-1]]
        for owner in dict.fromkeys(owners):
            if not arm_ik._registration(owner):continue
            module=arm_ik._switch_module(owner);data=module._data(owner)
            assert owner in arm_ik._callbacks,('missing callback',owner)
            initial=int(c.getAttr(data['global_plug'])>=.5)
            for mode in (1-initial,initial):
                before=pose(rig)
                module.switch(owner,mode,key=False)
                assert delta(before)<2e-5,('space pose',owner,delta(before))
                assert all(delta(p)<2e-5 for p in other),('space isolation',owner)
                mode_cases.append(owner)
        # Constraint ownership resolves to this reference, not the original.
        part=rig['parts']['arm_L'];control=part['zero_controls']['shoulder_fk']
        assert external_constraints.resolve(control)['root']==part['root']
        goal=c.createNode('transform',name='referenceExternalGoal')
        c.xform(goal,ws=True,m=c.xform(control,q=True,ws=True,m=True))
        before=pose(rig)
        external_constraints.attach(control,goal,kind='parent',native=True)
        registry=external_constraints.registry(control)
        constraint=external_constraints._link(registry,'constraint')
        c.setAttr(goal+'.ry',9);c.delete(constraint);c.delete(goal)
        assert delta(before)<2e-5,('constraint restore',delta(before))
        assert all(delta(p)<2e-5 for p in other),'constraint isolation'
    current_curves=curves()
    differences={n:dict(before=original_curves.get(n),after=current_curves.get(n))
                 for n in set(original_curves)|set(current_curves) if original_curves.get(n)!=current_curves.get(n)}
    (out/'reference-curve-differences.json').write_text(json.dumps(differences,indent=2),encoding='utf-8')
    assert not differences,'existing animation curves changed'
    assert all(c.getAttr(p)==v for p,v in texts.items()),'saved metadata was rewritten'
    # Persist the referencing scene, reopen, unload/reload, then select its head.
    saved=out/'reference-roundtrip.ma'
    c.file(rename=str(saved));c.file(save=True,type='mayaAscii',force=True)
    c.file(str(saved),open=True,force=True,executeScriptNodes=False)
    maya.utils.processIdleEvents()
    c.file(unloadReference=refs[0]);maya.utils.processIdleEvents()
    c.file(loadReference=refs[0]);maya.utils.processIdleEvents()
    rig=scene_data.read(roots[1]+'.integratedRigData')
    head=rig['parts']['head']['zero_controls']['head']
    c.select(head,r=True);live_edit.before_drag('manipRotate')
    assert live_edit._gesture
    live_edit.after_drag('manipRotate')
    assert rig['parts']['arm_L']['root'] in arm_ik._callbacks,'reload callbacks missing'
    # Reference the shot itself: both copies now live inside another reference.
    c.file(new=True,force=True)
    c.file(str(saved),reference=True,namespace='sequence',executeScriptNodes=False)
    maya.utils.processIdleEvents()
    nested=scene_data.read('sequence:'+roots[1]+'.integratedRigData')
    assert nested['root']=='sequence:'+roots[1],nested['root']
    for part,role in (('head','head'),('arm_L','shoulder_fk'),('leg_R','foot')):
        control=nested['parts'][part]['zero_controls'][role]
        c.select(control,r=True);before=pose(nested)
        live_edit.before_drag('manipRotate')
        assert live_edit._gesture
        c.setAttr(control+'.rotateY',c.getAttr(control+'.rotateY')+3)
        live_edit.update_drag(force=True);live_edit.after_drag('manipRotate');c.undo()
        assert delta(before)<2e-5,('nested undo',part,delta(before))
    om.MMessage.removeCallback(callback)
    missing=[m for m in messages if 'No object matches name' in m or '找不到对象' in m]
    assert not missing,missing
    return dict(passed=True,references=2,original_present=True,gesture_cases=len(cases),
                space_switches=len(mode_cases),constraints=True,animation_unchanged=True,
                metadata_unchanged=True,save_reopen_reload=True,nested_reference=True,missing_object_warnings=missing)
