"""Disposable routing regressions in the running Maya, no user scene edits."""
import json
import runpy
import traceback
import uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

BASE=Path(__file__).resolve().parents[1]


def run(animated=False,extra=None):
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import live_edit,live_arm_manual,zero_channels,arm_ik,foot_space
    suite=runpy.run_path(str(BASE/'scripts/test_integrated_rig_live.py'))
    curves=runpy.run_path(str(BASE/'scripts/test_external_constraints_live.py'))['_curves']
    original=set(c.ls(uuid=True));original_curves=curves(c.ls(type='animCurve') or [])
    selection=c.ls(sl=True,l=True) or [];frame=c.currentTime(q=True);context=c.currentCtx()
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    fixture=rig=None;report={'animated':animated,'extra':extra,'cases':[]}
    layer_flags={n:{a:c.animLayer(n,q=True,**{a:True}) for a in ('selected','preferred')}
                 for n in c.ls(type='animLayer') or []}
    edit_layer=None;constraints=[]
    def pose(nodes):return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def error(wanted):return max(abs(a-b) for n,m in wanted.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
    c.autoKeyframe(state=False)
    try:
        prefix='_footMove_'+uuid.uuid4().hex[:8]
        fixture,parts=suite['fixture'](prefix,animated)
        parts={k:p for k,p in parts.items() if k.startswith('leg')}
        for p in parts.values():p.update(live_alignment=True,space_foot=True,space_knee=True)
        c.currentTime(3);rig=build(parts,namespace=prefix,zero_controls=True)
        watched=[n for p in rig['parts'].values() for n in p['joints']]
        for p in rig['parts'].values():
            for role,axis,value in (('foot','ry',23),('heel','rx',7),('toe_end','rz',-9),('ball','ry',8)):
                n=p['zero_controls'][role];c.setAttr(n+'.'+axis,c.getAttr(n+'.'+axis)+value)
                if animated:c.setKeyframe(n,at=axis,t=3)
        if extra=='layer':
            for layer in layer_flags:c.animLayer(layer,e=True,selected=False,preferred=False)
            edit_layer=c.animLayer(prefix+'_edit',weight=.5,selected=True,preferred=True)
            for p in rig['parts'].values():
                foot=p['zero_controls']['foot']
                c.animLayer(edit_layer,e=True,attribute=[foot+'.translate'+a for a in 'XYZ'])
                c.setKeyframe(foot,at=['tx','ty','tz'],t=3,animLayer=edit_layer)
        if extra=='constraint':
            from maya_agent.rigs import external_constraints
            target=c.createNode('transform',name=prefix+'_target',parent=fixture)
            c.setAttr(target+'.rotate',19,31,-7)
            for p in rig['parts'].values():
                foot=p['zero_controls']['foot'];external_constraints.attach(foot,target)
                constraints.append(foot)
        c.setToolTo('moveSuperContext')
        for side in ('L','R'):
            part=rig['parts']['leg_'+side];controls=part['zero_controls'];foot=controls['foot']
            source=json.loads(c.getAttr(part['root']+'.liveAlignmentData'))['inputs']['foot']
            for mode in (0,1):
                c.autoKeyframe(state=False);foot_space.switch(part['root'],mode,key=animated)
                for roles in (('heel',),('toe_end',),('ball',),('heel','ball','toe_end'),('ball','foot')):
                    basepose=pose(watched)
                    plugs=[n+'.'+attr for n in controls.values() for attr in live_edit.TR if not c.getAttr(n+'.'+attr,lock=True)]
                    values={p:c.getAttr(p) for p in plugs};saved=curves(c.ls(type='animCurve') or [])
                    delta=om.MVector(.21,.13,-.17)
                    local=delta*om.MMatrix(c.getAttr(source+'.parentMatrix[0]')).inverse()
                    for axis,dv in zip('XYZ',local):c.setAttr(foot+'.translate'+axis,values[foot+'.translate'+axis]+dv)
                    expected=pose(watched)
                    for axis in 'XYZ':c.setAttr(foot+'.translate'+axis,values[foot+'.translate'+axis])
                    assert error(basepose)<1e-6
                    c.select([controls[role] for role in roles],r=True);c.autoKeyframe(state=animated)
                    live_edit.before_drag('test')
                    if edit_layer:assert live_edit._gesture['anim_layer']==edit_layer
                    entries=live_edit._gesture['arm_gestures']
                    for fraction in (.35,1.0):
                        for entry in entries:
                            live_arm_manual.prepare_native_sample(entry,suspend=False)
                            movement=(delta*fraction)*entry['parent'].inverse()
                            for axis,start,dv in zip('XYZ',entry['native_start'],movement):
                                c.setAttr(entry['proxy']+'.translate'+axis,start+dv)
                        live_edit.update_drag(force=True)
                    held=pose(watched);assert error(expected)<1e-5,(side,mode,roles,'held',error(expected))
                    live_edit.after_drag('test')
                    assert error(held)<1e-5,(side,mode,roles,'release')
                    for p,v in values.items():
                        if p.startswith(foot+'.translate'):continue
                        assert abs(c.getAttr(p)-v)<1e-7,(p,c.getAttr(p),v)
                    if animated:
                        c.undoInfo(stateWithoutFlush=False)
                        try:c.currentTime(3.5);c.currentTime(3)
                        finally:c.undoInfo(stateWithoutFlush=True)
                        assert error(held)<1e-5,(roles,'replay',error(held))
                    c.undo();assert error(basepose)<1e-5,('undo pose',roles)
                    assert curves(saved)==saved,('undo curves',roles)
                    c.redo();assert error(held)<1e-5,('redo',roles);c.undo()
                    report['cases'].append(dict(side=side,mode=mode,roles=roles,passed=True))
        # Clicking without moving must not alter any input or key.
        c.autoKeyframe(state=animated);c.select(rig['parts']['leg_L']['zero_controls']['heel'],r=True)
        baseline=pose(watched);saved=curves(c.ls(type='animCurve') or [])
        live_edit.before_drag('test');live_edit.after_drag('test')
        assert error(baseline)<1e-6 and curves(saved)==saved
        report['no_op']=True
        # Rotation still belongs to the chosen roll controller, not the foot.
        c.autoKeyframe(state=False);c.setToolTo('RotateSuperContext')
        for role in ('heel','toe_end','ball'):
            p=rig['parts']['leg_L'];handle=p['zero_controls'][role];foot=p['zero_controls']['foot']
            foot_before=c.getAttr(foot+'.translate')[0]
            c.select(handle,r=True);live_edit.before_drag('test')
            assert not any(e.get('foot_move') for e in live_edit._gesture['arm_gestures'])
            c.setAttr(handle+'.rx',c.getAttr(handle+'.rx')+4);live_edit.update_drag(force=True)
            held=pose(watched);live_edit.after_drag('test')
            assert error(held)<1e-5
            assert c.getAttr(foot+'.translate')[0]==foot_before
            c.undo()
        report['rotation_preserved']=True;report['passed']=True
    except Exception:
        report['passed']=False;report['traceback']=traceback.format_exc()
    finally:
        if live_edit._gesture:
            for entry in reversed(live_edit._gesture['arm_gestures']):live_arm_manual.finish(entry,cancel=True)
            live_edit.after_drag('test')
        c.autoKeyframe(state=False)
        for foot in constraints:
            from maya_agent.rigs import external_constraints
            external_constraints.remove(foot)
        for layer in reversed(c.ls(type='animLayer') or []):
            if layer not in layer_flags and c.objExists(layer):c.delete(layer)
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        for uid in set(c.ls(uuid=True))-original:
            nodes=c.ls(uid,l=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):c.delete(nodes[0])
        c.currentTime(frame);c.select(selection,r=True) if selection else c.select(clear=True)
        c.setToolTo(context);c.autoKeyframe(state=auto);arm_ik.install()
        for layer,flags in layer_flags.items():c.animLayer(layer,e=True,**flags)
        report['original_nodes_preserved']=set(c.ls(uuid=True))==original
        report['original_curves_preserved']=curves(original_curves)==original_curves
        c.file(modified=modified)
        name='foot-translation-'+(extra or ('animated' if animated else 'static'))+'.json'
        (BASE/'outputs'/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
