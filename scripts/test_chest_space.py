"""Chest matching, all four body states, native panel keys and earlier poses."""
import maya.cmds as c
from scripts import test_body_direction as fixture
from maya_agent.rigs import chest_space,zero_channels,switch_panel,arm_ik,live_edit


def verify(count=4,layer=False):
    try:
        p=fixture.setup(count=count,animated=True,general=True)
        zero_channels.build(fixture.state['assembly']);panel=switch_panel.build(fixture.state['assembly']['root'])
        h=p['zero_controls']['hips'];ch=p['zero_controls']['chest'];raw=p['controls']['chest']
        # Establish previous mode keys explicitly; the switch must never add one.
        c.currentTime(6);c.setAttr(h+'.rotate',20,-25,30);c.setAttr(ch+'.translate',2,3,-1)
        c.setKeyframe(list(p['zero_controls'].values()));c.setKeyframe(raw+'.global',v=0)
        before=fixture.pose();old_curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        if layer:
            l=c.animLayer('_chestSwitchLayer',selected=True,preferred=True,weight=.5)
            attrs=[n+'.'+a for n in p['zero_controls'].values() for a in live_edit.TR]+[raw+'.global',p['controls']['hips']+'.bodyDrive']
            c.animLayer(l,e=True,attribute=attrs);c.setKeyframe(attrs,animLayer=l)
        old_times={n:set(c.keyframe(n,q=True,tc=True) or []) for n in c.ls(type='animCurve')}
        reports=[]
        for f,role,mode in [(10,'chest',1),(15,'hips',1),(20,'chest',0),(25,'hips',0),(30,'chest',1),(35,'chest',0)]:
            c.currentTime(f);pose=fixture.pose();report=switch_panel.apply(panel['sliders'][role],mode,key=True)
            assert fixture.error(pose,fixture.pose())<1e-5
            held=fixture.pose();c.currentTime(f+.5);c.currentTime(f)
            assert fixture.error(held,fixture.pose())<1e-5
            reports.append(report)
        c.currentTime(6);assert fixture.error(before,fixture.pose())<1e-5
        added={t for n in c.ls(type='animCurve') for t in set(c.keyframe(n,q=True,tc=True) or [])-old_times.get(n,set())}
        assert added<={10.,15.,20.,25.,30.,35.},added
        if layer:
            assert all((c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==v for n,v in old_curves.items())
        c.currentTime(40);handle=panel['sliders']['chest'];c.select(handle);c.setKeyframe()
        d=switch_panel._read(handle,'spaceSliderData')
        assert all(40 in (c.keyframe(p,q=True,tc=True) or []) for p in list(d['key_proxies'].values())+[d['plug']])
        assert not c.keyframe(handle+'.tx',q=True,tc=True)
        count_nodes=len(c.ls());switch_panel.upgrade(panel['root']);assert len(c.ls())==count_nodes
        assert c.getAttr(panel['sliders']['hips']+'.translateX')==0
        return dict(count=count,layer=layer,max_error=max(x['max_pose_error'] for x in reports),added_frames=sorted(added),panel_keys=True)
    finally:
        if fixture.state:fixture.cleanup()


def setup_native():
    import maya.utils,functools
    p=fixture.setup(animated=True);zero_channels.build(fixture.state['assembly'])
    c.currentTime(14);c.setAttr(p['zero_controls']['hips']+'.rotate',20,-25,30)
    c.setAttr(p['zero_controls']['chest']+'.translate',2,3,-1)
    c.setKeyframe(list(p['zero_controls'].values()))
    fixture.state['native_pose']=fixture.pose();c.autoKeyframe(state=True);arm_ik.install();arm_ik._sync_mode_cache()
    maya.utils.executeDeferred(functools.partial(c.setAttr,p['zero_controls']['chest']+'.global',1))


def check_native(mode):
    p=fixture.state['rig'];error=fixture.error(fixture.state['native_pose'],fixture.pose())
    assert c.getAttr(p['controls']['chest']+'.global')==mode and error<1e-5,error
    return dict(mode=mode,error=error)
