"""Body rotation must preserve authored translation and permit natural bending."""
import math
import maya.cmds as c
from scripts import test_body_direction as fixture
from maya_agent.rigs import zero_channels,live_edit,live_arm_manual,body_direction,chest_space


def verify(count=4,layer=False):
    context=c.currentCtx();reports=[]
    try:
        p=fixture.setup(count=count,animated=True,general=True)
        zero_channels.build(fixture.state['assembly'])
        controls=p['zero_controls'];hips=p['controls']['hips'];chest=p['controls']['chest']
        c.currentTime(3)
        c.setAttr(controls['chest']+'.translateX',1.3)
        c.setKeyframe(controls['chest']+'.translateX')
        if layer:
            for n in c.ls(type='animLayer'):c.animLayer(n,e=True,selected=False,preferred=False)
            edit=c.animLayer(p['namespace']+'_edit',weight=.5,selected=True,preferred=True)
            c.animLayer(edit,e=True,attribute=[n+'.rotate'+a for n in controls.values() for a in 'XYZ'])
            c.setKeyframe(list(controls.values()),at=['rx','ry','rz'],animLayer=edit)
        for mode,space in ((0,0),(0,1),(1,1),(1,0)):
            c.autoKeyframe(state=False)
            chest_space.switch(chest,space,key=False);body_direction.switch(hips,mode,key=False)
            for role in controls:
                ctrl=controls[role]
                translations={n:c.getAttr(n+'.translate')[0] for n in controls.values()}
                curve_plugs=[n+'.translate'+a for n in controls.values() for a in 'XYZ']
                curves={plug:(c.keyframe(plug,q=True,tc=True),c.keyframe(plug,q=True,vc=True)) for plug in curve_plugs}
                for axis in 'XYZ':
                    c.select(ctrl);c.setToolTo('RotateSuperContext');c.autoKeyframe(state=True)
                    before=fixture.pose();live_edit.before_drag('body-rotation')
                    for angle in (5,12):
                        c.setAttr(ctrl+'.rotate'+axis,angle);live_edit.update_drag(force=True)
                    moved=fixture.pose();live_edit.after_drag('body-rotation')
                    assert fixture.error(moved,fixture.pose())<1e-5
                    assert all(max(abs(a-b) for a,b in zip(c.getAttr(n+'.translate')[0],v))<1e-8 for n,v in translations.items())
                    assert all((c.keyframe(plug,q=True,tc=True),c.keyframe(plug,q=True,vc=True))==v for plug,v in curves.items())
                    # The fixed endpoint is allowed to remain still; the bending
                    # endpoint must actually travel, as the original rig does.
                    if (mode==0 and space==0 and role=='chest' or mode==1 and role=='hips') and count>2:
                        travel=math.dist(before[p['controls'][role]][12:15],moved[p['controls'][role]][12:15])
                        assert travel>1e-4,(mode,space,role,axis,travel)
                    reports.append((mode,space,role,axis))
        # Replay of held translations on the same frame must not add movement.
        authored={n:c.getAttr(n+'.translate')[0] for n in controls.values()}
        c.currentTime(4);c.currentTime(3)
        assert all(max(abs(a-b) for a,b in zip(c.getAttr(n+'.translate')[0],v))<1e-8 for n,v in authored.items())
        assert not live_edit._gesture
        return dict(count=count,half_weight_layer=layer,rotation_cases=len(reports),translation_values_and_curves_preserved=True)
    finally:
        if live_edit._gesture:
            for e in live_edit._gesture['arm_gestures']:live_arm_manual.finish(e,cancel=True)
            live_edit.after_drag('body-rotation-cleanup')
        if fixture.state:fixture.cleanup()
        c.setToolTo(context)


def verify_native():
    from scripts.test_zero_native_probe import probe
    context=c.currentCtx()
    options={f:c.manipRotateContext('Rotate',q=True,**{f:True}) for f in ('mode','activeHandle','currentActiveHandle')}
    try:
        p=fixture.setup();zero_channels.build(fixture.state['assembly'])
        ctrl=p['zero_controls']['chest'];c.autoKeyframe(state=False)
        reports=[]
        for _ in range(2):
            phases=probe(ctrl,rotate=True)
            assert phases['fired']
            a=phases['before'];b=phases['released']
            assert max(abs(x-y) for x,y in zip(a['channels'][:3],b['channels'][:3]))<1e-8
            assert math.dist(a['pivot'],b['pivot'])>1e-5
            assert math.dist(phases['release_event']['pivot'],b['pivot'])<1e-5
            reports.append(dict(translation=b['channels'][:3],world_travel=math.dist(a['pivot'],b['pivot'])))
        return reports
    finally:
        if live_edit._gesture:live_edit.after_drag('native-cleanup')
        if fixture.state:fixture.cleanup()
        c.manipRotateContext('Rotate',e=True,**options);c.setToolTo(context)
