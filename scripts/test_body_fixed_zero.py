"""Fixed rest, native current-frame keys, and no automatically created layers."""
import json
import maya.cmds as c
from scripts import test_body_direction as fixture
from maya_agent.rigs import zero_channels,body_direction,chest_space,live_edit,body_zero


def verify(count=4,animated=False,layer=False):
    try:
        p=fixture.setup(count=count,animated=animated,general=True)
        zero_channels.build(fixture.state['assembly']);z=p['zero_controls']
        h=p['controls']['hips'];ch=p['controls']['chest'];rest=fixture.pose()
        def zero():
            for n in z.values():
                for a in live_edit.TR:c.setAttr(n+'.'+a,0)
        reports=[]
        for mode,space in ((1,0),(1,1),(0,1),(0,0),(1,0)):
            c.setAttr(z['hips']+'.translate',1,-2,.5);c.setAttr(z['hips']+'.rotate',8,12,-6)
            c.setAttr(z['chest']+'.translate',2,3,-1);c.setAttr(z['chest']+'.rotate',15,-20,10)
            before=fixture.pose();a=body_direction.switch(h,mode,key=False)
            assert fixture.error(before,fixture.pose())<1e-5
            before=fixture.pose();b=chest_space.switch(ch,space,key=False)
            assert fixture.error(before,fixture.pose())<1e-5
            c.setAttr(z['chest']+'.rotateX',c.getAttr(z['chest']+'.rotateX')+12)
            c.setAttr(z['hips']+'.translateZ',c.getAttr(z['hips']+'.translateZ')+2)
            zero();error=fixture.error(rest,fixture.pose());assert error<1e-5,error
            reports.append(error)
        body_direction.switch(h,0,key=False);chest_space.switch(ch,0,key=False);zero()
        c.currentTime(6);c.setKeyframe(list(z.values()));c.setKeyframe([h+'.bodyDrive',ch+'.global'])
        c.currentTime(8);c.setAttr(z['chest']+'.translate',2,3,-1);c.setAttr(z['chest']+'.rotate',15,-20,10);c.setKeyframe(list(z.values()))
        original_curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        if layer:
            for n in c.ls(type='animLayer'):c.animLayer(n,e=True,selected=False,preferred=False)
            edit=c.animLayer(p['namespace']+'_edit',weight=.5,selected=True,preferred=True)
            attrs=[n+'.'+a for n in z.values() for a in live_edit.TR]+[h+'.bodyDrive',ch+'.global']
            c.animLayer(edit,e=True,attribute=attrs);c.setKeyframe(attrs,animLayer=edit)
        samples={}
        for f in (6,7,8,8.5,9,9.99,10):c.currentTime(f);samples[f]=fixture.pose()
        old_times={n:set(c.keyframe(n,q=True,tc=True) or []) for n in c.ls(type='animCurve')}
        old_layers=set(c.ls(type='animLayer') or [])
        c.currentTime(10);body_direction.switch(h,1,key=True)
        assert fixture.error(samples[10],fixture.pose())<1e-5
        # Matching now uses ordinary curves. Earlier authored key values stay
        # intact, while their interpolation into the new switch key may change.
        for f,control,value in ((12,ch,1),(14,h,0),(16,ch,0),(18,h,1)):
            c.currentTime(f);pose=fixture.pose()
            (chest_space if control==ch else body_direction).switch(control,value,key=True)
            assert fixture.error(pose,fixture.pose())<1e-5
            c.currentTime(f+.5);c.currentTime(f);assert fixture.error(pose,fixture.pose())<1e-5
        for n,(times,values) in original_curves.items():
            for t,v in zip(times or [],values or []):assert abs(c.keyframe(n,q=True,time=(t,t),vc=True)[0]-v)<1e-8
        assert set(c.ls(type='animLayer') or [])==old_layers
        added={t for n in c.ls(type='animCurve') for t in set(c.keyframe(n,q=True,tc=True) or [])-old_times.get(n,set())}
        assert added=={10.,12.,14.,16.,18.},added
        c.currentTime(20);zero();err=fixture.error(rest,fixture.pose());assert err<1e-5,err
        # Record the reset on the native selected layer and revisit it.
        c.setKeyframe(list(z.values()),at=list(live_edit.TR))
        c.currentTime(21);c.currentTime(20);assert fixture.error(rest,fixture.pose())<1e-5
        return dict(count=count,animated=animated,half_weight_layer=layer,reset_error=max(reports+[err]),old_key_values_preserved=True,no_new_layers=True,added_frames=sorted(added))
    finally:
        if fixture.state:fixture.cleanup()


def verify_rollback():
    from maya_agent.rigs import body_direction_match
    try:
        p=fixture.setup();zero_channels.build(fixture.state['assembly'])
        h=p['controls']['hips'];c.setAttr(p['zero_controls']['chest']+'.rx',20)
        before=fixture.pose();nodes=set(c.ls(long=True));metadata=c.getAttr(h+'.bodyDriveData')
        check=body_direction_match._check_pose
        def fail(*args,**kw):raise RuntimeError('injected match failure')
        body_direction_match._check_pose=fail
        try:
            try:body_direction.switch(h,1,key=True)
            except RuntimeError as e:assert 'injected match failure' in str(e)
            else:raise AssertionError('Failure was not propagated')
        finally:body_direction_match._check_pose=check
        assert c.getAttr(h+'.bodyDriveData')==metadata
        assert set(c.ls(long=True))==nodes,sorted(set(c.ls(long=True))-nodes)
        assert fixture.error(before,fixture.pose())<1e-5
        return dict(rollback=True)
    finally:
        if fixture.state:fixture.cleanup()


undo_result=None


def verify_undo():
    """Run deferred, outside the MCP chunk; only undo our named test chunk."""
    global undo_result
    undo_result=None
    try:
        p=fixture.setup();zero_channels.build(fixture.state['assembly']);h=p['controls']['hips']
        c.setAttr(p['zero_controls']['chest']+'.translate',2,3,-1)
        c.setAttr(p['zero_controls']['hips']+'.rotate',15,20,-12)
        before=fixture.pose();metadata=c.getAttr(h+'.bodyDriveData')
        c.undoInfo(openChunk=True,chunkName='TestFixedBodyZeroSwitch')
        try:body_direction.switch(h,1,key=True)
        finally:c.undoInfo(closeChunk=True)
        after=fixture.pose();matched_data=c.getAttr(h+'.bodyDriveData')
        undo_name=c.undoInfo(q=True,undoName=True)
        assert undo_name in ('TestFixedBodyZeroSwitch','MatchFixedBodyZero'),undo_name
        c.undo();assert fixture.error(before,fixture.pose())<1e-5
        assert c.getAttr(h+'.bodyDriveData')==metadata
        c.redo();assert fixture.error(after,fixture.pose())<1e-5
        assert c.getAttr(h+'.bodyDriveData')==matched_data
        undo_result=dict(undo=True,redo=True)
    except Exception:
        import traceback
        undo_result=dict(error=traceback.format_exc())
    finally:
        if fixture.state:fixture.cleanup()
