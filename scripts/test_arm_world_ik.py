"""World wrist planting and seamless switches on disposable L/R soft arms."""
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import arm_ik,live_edit

state=None


def setup(animated=False,callbacks=False,live=True,general=False):
    global state
    state=dict(nodes=set(c.ls(long=True)),frame=c.currentTime(q=True),auto=c.autoKeyframe(q=True,state=True),
               selection=c.ls(sl=True,long=True) or [],rig=None,tool=c.currentCtx(),layers={})
    for l in c.ls(type='animLayer') or []:
        state['layers'][l]={a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')}
        c.animLayer(l,e=True,selected=False,preferred=False)
    base=c.animLayer(q=True,root=True)
    if base:c.animLayer(base,e=True,selected=True,preferred=True)
    c.autoKeyframe(state=False);prefix='_worldIKTest_'+uuid.uuid4().hex[:6]
    fixture_root,parts=fixture(prefix,animated)
    for k in ('arm_L','arm_R'):parts[k].update(space_wrist=True,space_upper_arm=True,live_alignment=live)
    if animated:c.currentTime(3)
    state['rig']=build({k:p for k,p in parts.items() if k in ('body','arm_L','arm_R')},namespace=prefix,general_root=fixture_root if general else None)
    state['arms']={k:p for k,p in state['rig']['parts'].items() if k.startswith('arm')}
    state['data']={k:arm_ik.enable(p,callbacks=callbacks) for k,p in state['arms'].items()}
    return dict(ready=True)


def pose(key):
    p=state['arms'][key]
    nodes=p['joints']+[m['target'] for m in p.get('original_target_mapping',[])]
    return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}


def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))


def verify(animated=False):
    reports=[]
    try:
        setup(animated)
        for key,p in state['arms'].items():
            d=state['data'][key];before=pose(key)
            r=arm_ik.switch(p['root'],1,key=False);into=error(before,pose(key))
            wrist=p['joints'][-1];target=p['original_target_mapping'][-1]['target']
            fixed={n:c.xform(n,q=True,ws=True,m=True) for n in (wrist,target,d['controls']['wrist'])}
            chest=state['rig']['parts']['body']['controls']['chest'];old=c.getAttr(chest+'.translateX')
            c.setAttr(chest+'.translateX',old+(.25 if key=='arm_L' else -.25))
            c.rotate(7,-4,9,chest,r=True)
            held=max(abs(a-b) for n,m in fixed.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
            before_back=pose(key);r2=arm_ik.switch(p['root'],0,key=False);back=error(before_back,pose(key))
            assert max(into,held,back)<1e-5,(key,into,held,back)
            reports.append(dict(part=key,into=into,world_hold=held,back=back))
        return reports
    finally:cleanup()


def cleanup():
    global state
    c.autoKeyframe(state=False)
    if state['rig']:remove(state['rig'])
    for n in sorted(set(c.ls(long=True))-state['nodes'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    arm_ik.install()
    c.currentTime(state['frame']);c.setToolTo(state['tool'])
    for l,flags in state['layers'].items():c.animLayer(l,e=True,**flags)
    c.autoKeyframe(state=state['auto']);c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    state=None


def verify_animation(override=False,weight=1.0,layered=True):
    """Switch/replay both sides and retain all preexisting base curves."""
    from maya_agent.rigs import live_layers
    reports=[]
    try:
        setup(True)
        base_curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))
                     for n in c.ls(type='animCurve')}
        layer=None
        if layered:
            for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
            layer=c.animLayer('_worldIKTestLayer',override=override)
            c.animLayer(layer,e=True,weight=weight,selected=True,preferred=True)
        for key,p in state['arms'].items():
            d=state['data'][key];c.currentTime(10);before=pose(key)
            arm_ik.switch(p['root'],1,key=True)
            assert error(before,pose(key))<1e-5
            nodes=[p['joints'][-1],p['original_target_mapping'][-1]['target'],d['controls']['wrist']]
            fixed={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
            # Animate the fixture chest while each world wrist stays planted.
            chest=state['rig']['parts']['body']['controls']['chest']
            c.setKeyframe(chest,at='translateX',t=10,v=0,animLayer=c.animLayer(q=True,root=True))
            c.setKeyframe(chest,at='translateX',t=20,v=.2,animLayer=c.animLayer(q=True,root=True))
            worst=0
            for f in (10,10.25,12.5,15,19,20):
                c.currentTime(f)
                assert arm_ik._mode(c.getAttr(d['global_plug']))==1,(key,f,c.getAttr(d['global_plug']))
                worst=max(worst,error(fixed,{n:c.xform(n,q=True,ws=True,m=True) for n in nodes}))
            assert worst<1e-5,(key,'plant',worst)
            before=pose(key);arm_ik.switch(p['root'],0,key=True)
            assert error(before,pose(key))<1e-5,(key,'back')
            c.currentTime(21);c.currentTime(20)
            assert error(before,pose(key))<1e-5,(key,'back replay',error(before,pose(key)))
            c.currentTime(15)
            assert arm_ik._mode(c.getAttr(d['global_plug']))==1
            assert error(fixed,{n:c.xform(n,q=True,ws=True,m=True) for n in nodes})<1e-5
            reports.append(dict(part=key,world_hold=worst))
        if layer:
            # Chest keys are an intentional fixture animation edit; arm base
            # curves and all actual user curves must remain byte-for-byte values.
            changed=[n for n,old in base_curves.items() if not n.startswith(state['rig']['parts']['body']['namespace']+':')
                     and (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))!=old]
            assert not changed,changed
            c.animLayer(layer,e=True,mute=True)
            assert all(c.getAttr(d['global_plug'])==0 for d in state['data'].values())
        return dict(override=override,weight=weight,layered=layered,arms=reports)
    finally:
        if state:cleanup()


def verify_controls(live=True,general=False):
    try:
        setup(True,live=live,general=general);reports=[]
        for key,p in state['arms'].items():
            d=state['data'][key];arm_ik.switch(p['root'],1,key=False)
            wrist=d['controls']['wrist'];pole=d['controls']['pole']
            # Native transforms use Maya directly: no live calibration callback.
            for _ in range(3):
                c.move(.15,.1,-.12,wrist,r=True,ws=True);c.rotate(3,-2,5,wrist,r=True,os=True)
                c.move(0,0,.2,pole,r=True,ws=True)
            before=pose(key);arm_ik.switch(p['root'],0,key=False);back=error(before,pose(key))
            assert back<1e-5,back
            arm_ik.switch(p['root'],1,key=False)
            nodes=[p['joints'][-1],p['original_target_mapping'][-1]['target'],wrist]
            fixed={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
            driver=state['rig']['general_root'] if general else state['rig']['parts']['body']['controls']['chest']
            c.move(.3,.2,-.4,driver,r=True,ws=True);c.rotate(8,3,-5,driver,r=True,os=True)
            held=error(fixed,{n:c.xform(n,q=True,ws=True,m=True) for n in nodes})
            assert held<1e-5,held
            reports.append(dict(part=key,return_error=back,hold=held))
        return dict(live=live,general=general,reports=reports)
    finally:
        if state:cleanup()


def verify_shared_wrist(live=True,layered=False):
    from maya_agent.rigs import live_arm_manual,live_layers
    try:
        setup(True,live=live);reports=[]
        layer=None
        if layered:
            for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
            layer=c.animLayer('_sharedWristLayer');c.animLayer(layer,e=True,selected=True,preferred=True)
        for key,p in state['arms'].items():
            d=arm_ik._data(p['root']);ctrl=d['fk_wrist'];c.select(ctrl)
            arm_ik.switch(p['root'],1,key=True)
            assert c.ls(sl=True)==[ctrl]
            for mode in ('move','rotate'):
                c.select(ctrl);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
                c.autoKeyframe(state=True);before=pose(key)
                live_edit.before_drag('shared-wrist-test')
                assert live_edit._gesture
                press=error(before,pose(key))
                if mode=='move':c.move(.2,.15,-.1,ctrl,r=True,ws=True)
                else:c.rotate(5,-3,7,ctrl,r=True,os=True)
                live_edit.update_drag();during=pose(key);live_edit.after_drag('shared-wrist-test')
                release=error(during,pose(key));c.currentTime(4);c.currentTime(3);scrub=error(during,pose(key))
                assert max(press,release,scrub)<1e-5,(key,mode,press,release,scrub)
                assert error(before,during)>1e-4
                reports.append(dict(part=key,mode=mode,press=press,release=release,scrub=scrub))
            arm_ik.switch(p['root'],0,key=False)
        return dict(live=live,layered=layered,reports=reports)
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        if state:cleanup()
