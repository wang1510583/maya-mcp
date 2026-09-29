"""Foot world/hips switching on disposable left/right rigs in the active scene."""
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import foot_space,arm_ik,live_edit

state=None


def setup(animated=False,live=True,external=False):
    global state
    state=dict(nodes=set(c.ls(long=True)),time=c.currentTime(q=True),auto=c.autoKeyframe(q=True,state=True),
               selection=c.ls(sl=True,long=True) or [],layers={},rig=None)
    for layer in c.ls(type='animLayer') or []:
        state['layers'][layer]={a:c.animLayer(layer,q=True,**{a:True}) for a in ('selected','preferred')}
        c.animLayer(layer,e=True,selected=False,preferred=False)
    base=c.animLayer(q=True,root=True)
    if base:c.animLayer(base,e=True,selected=True,preferred=True)
    c.autoKeyframe(state=False);prefix='_footSpaceTest_'+uuid.uuid4().hex[:7]
    _,parts=fixture(prefix,animated)
    for key in ('leg_L','leg_R'):parts[key].update(space_foot=True,space_knee=True,live_alignment=live)
    c.currentTime(3 if animated else 1)
    hips=parts['body']['targets'][0] if external else None
    state['rig']=build({k:p for k,p in parts.items() if k in (('leg_R','leg_L') if external else ('body','leg_R','leg_L'))},namespace=prefix,hips_follow=hips)
    state['legs']={k:p for k,p in state['rig']['parts'].items() if k.startswith('leg')}
    state['hips']=hips or state['rig']['parts']['body']['controls']['hips']
    for part in state['legs'].values():
        space=next(s for s in state['rig']['spaces'] if s['control']==part['controls']['foot']);foot_space.enable(part,space)


def pose(part):
    nodes=part['joints']+[m['target'] for m in part.get('original_target_mapping',[])]
    return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}


def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))


def verify(animated=False,live=True,external=False):
    import maya.api.OpenMaya as om
    reports=[]
    try:
        setup(animated,live,external)
        for key,p in state['legs'].items():
            foot=p['controls']['foot'];hips=state['hips']
            initial=c.xform(foot,q=True,ws=True,m=True)
            c.move(.15,.2,-.1,hips,r=True,ws=True);c.rotate(3,-2,4,hips,r=True,os=True)
            held=max(abs(a-b) for a,b in zip(initial,c.xform(foot,q=True,ws=True,m=True)))
            before=pose(p);a=foot_space.switch(p['root'],1,key=False);into=error(before,pose(p))
            frame=om.MMatrix(c.xform(hips,q=True,ws=True,m=True));start=om.MMatrix(c.xform(foot,q=True,ws=True,m=True))
            c.move(.15,-.1,.2,hips,r=True,ws=True);c.rotate(-2,4,3,hips,r=True,os=True)
            expected=start*frame.inverse()*om.MMatrix(c.xform(hips,q=True,ws=True,m=True))
            followed=max(abs(a-b) for a,b in zip(expected,c.xform(foot,q=True,ws=True,m=True)))
            before=pose(p);b=foot_space.switch(p['root'],0,key=False);back=error(before,pose(p))
            assert max(held,into,followed,back)<1e-5,(key,held,into,followed,back)
            reports.append(dict(part=key,held=held,enter=into,follow=followed,return_error=back))
        return dict(animated=animated,live=live,external=external,reports=reports)
    finally:
        if state:cleanup()


def cleanup():
    global state
    c.autoKeyframe(state=False)
    if state['rig']:remove(state['rig'])
    for n in sorted(set(c.ls(long=True))-state['nodes'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    for layer,flags in state['layers'].items():c.animLayer(layer,e=True,**flags)
    c.currentTime(state['time']);c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    c.autoKeyframe(state=state['auto']);arm_ik.install();state=None


def verify_animation(override=False,weight=1.0):
    try:
        setup(True);reports=[]
        before_curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
        layer=c.animLayer('_footSpaceLayer',override=override);c.animLayer(layer,e=True,selected=True,preferred=True,weight=weight)
        for key,p in state['legs'].items():
            c.currentTime(10);a=foot_space.switch(p['root'],1,key=True);matched=pose(p)
            c.currentTime(11);c.currentTime(10);replay=error(matched,pose(p));assert replay<1e-5,(key,replay)
            c.currentTime(15);b=foot_space.switch(p['root'],0,key=True);matched=pose(p)
            c.currentTime(16);c.currentTime(15);back=error(matched,pose(p));assert back<1e-5,(key,back)
            for f in (9,9.75,10,12.5,14.75,15):
                c.currentTime(f);value=c.getAttr(p['controls']['foot']+'.global');assert value==int(10<=f<15),(f,value)
            reports.append(dict(part=key,enter=a,return_switch=b,replay=replay,return_replay=back))
        unchanged=before_curves=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in before_curves}
        assert unchanged,'Base curves changed'
        c.animLayer(layer,e=True,mute=True)
        assert all(c.getAttr(p['controls']['foot']+'.global')==0 for p in state['legs'].values())
        return dict(override=override,weight=weight,base_unchanged=unchanged,reports=reports)
    finally:
        if state:cleanup()


def setup_native(part='leg_L'):
    """Call, wait for idle, check_native(1), then defer undo/redo and check again.

    Finish with cleanup(). Kept separate so Maya records native edits outside
    the MCP command chunk and the real deferred observer runs normally.
    """
    import functools,maya.utils
    setup(True);p=state['legs'][part];c.currentTime(14)
    for role,v in [('heel',6),('toe_end',-8),('ball',9),('toe',3)]:
        c.setAttr(p['live_controls'][role]+'.rotateZ',v)
    c.setAttr(p['controls']['knee']+'.global',1)
    c.move(.4,.2,-.3,state['hips'],r=True,ws=True)
    c.rotate(4,8,-6,state['hips'],r=True,os=True)
    state['native_part']=p;state['native_pose']=pose(p)
    c.select(p['live_controls']['foot']);c.autoKeyframe(state=True)
    arm_ik._sync_mode_cache()
    maya.utils.executeDeferred(functools.partial(c.setAttr,p['live_controls']['foot']+'.global',1))


def check_native(mode):
    p=state['native_part'];delta=error(state['native_pose'],pose(p))
    value=c.getAttr(p['live_controls']['foot']+'.global')
    assert value==mode and delta<1e-5,(value,delta)
    return dict(mode=value,pose_error=delta)
