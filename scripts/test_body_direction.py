"""Body direction regression on disposable static/animated rigs."""
import uuid
import maya.cmds as c
from maya_agent.rigs import body_direction,arm_ik
from maya_agent.rigs.custom_body import build as build_body
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import remove

state=None


def setup(count=4,animated=False,standard=False,general=False):
    global state
    state=dict(nodes=set(c.ls(long=True)),time=c.currentTime(q=True),selection=c.ls(sl=True,long=True) or [],auto=c.autoKeyframe(q=True,state=True),layers={},rig=None,assembly=None)
    for l in c.ls(type='animLayer') or []:
        state['layers'][l]={a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')};c.animLayer(l,e=True,selected=False,preferred=False)
    base=c.animLayer(q=True,root=True)
    if base:c.animLayer(base,e=True,selected=True,preferred=True)
    c.autoKeyframe(state=False);prefix='_bodyDirectionTest_'+uuid.uuid4().hex[:6]
    if standard:state['rig']=build_body(namespace=prefix,segment_count=count)
    else:
        group=c.createNode('transform',name=prefix+'_source');targets=[]
        for i in range(count):
            n=c.createNode('joint',name=prefix+'_source'+str(i),parent=targets[-1] if targets else group)
            c.xform(n,ws=True,t=(i*.3,10+i*3,i*.1));c.xform(n,ws=True,ro=(3+i*2,5-i,2))
            targets.append(c.ls(n,long=True)[0])
            if animated:
                for attr in ('rx','ry','tx'):
                    v=c.getAttr(n+'.'+attr)
                    for f,d in ((1,0),(3,.1),(5,-.1)):c.setKeyframe(n,at=attr,t=f,v=v+d)
        c.currentTime(3 if animated else 1)
        state['assembly']=build({'body':dict(targets=targets,copy_animation=animated,start_frame=1,end_frame=5,space_chest=True)},namespace=prefix,general_root=group if general else None)
        state['rig']=state['assembly']['parts']['body']
    return state['rig']


def pose():
    rig=state['rig'];nodes=rig['joints']+list(rig['controls'].values())+[m['target'] for m in rig.get('original_target_mapping',[])]
    return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}


def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))


def cleanup():
    global state
    c.autoKeyframe(state=False)
    if state['assembly']:remove(state['assembly'])
    for n in sorted(set(c.ls(long=True))-state['nodes'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    c.currentTime(state['time'])
    for l,flags in state['layers'].items():c.animLayer(l,e=True,**flags)
    c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    c.autoKeyframe(state=state['auto']);arm_ik.install();state=None


def verify(count=4,animated=False,standard=False,general=False):
    try:
        rig=setup(count,animated,standard,general);h=rig['controls']['hips'];ch=rig['controls']['chest']
        if c.objExists(ch+'.global'):c.setAttr(ch+'.global',1)
        c.move(.3,.2,-.1,h,r=True,ws=True);c.rotate(7,-4,9,h,r=True,os=True)
        before=pose();a=body_direction.switch(h,1,key=False);enter=error(before,pose())
        old=c.xform(h,q=True,ws=True,t=True);c.move(.6,.3,-.2,ch,r=True,ws=True)
        delta=[a-b for a,b in zip(c.xform(h,q=True,ws=True,t=True),old)]
        assert max(abs(a-b) for a,b in zip(delta,(.6,.3,-.2)))<1e-5,delta
        old=c.xform(ch,q=True,ws=True,m=True);c.move(.3,-.2,.1,h,r=True,ws=True)
        held=max(abs(a-b) for a,b in zip(old,c.xform(ch,q=True,ws=True,m=True)));assert held<1e-5,held
        old=c.xform(h,q=True,ws=True,t=True);c.rotate(12,-8,9,ch,r=True,os=True)
        assert max(abs(a-b) for a,b in zip(old,c.xform(h,q=True,ws=True,t=True)))>.01
        before=pose();b=body_direction.switch(h,0,key=False);back=error(before,pose())
        assert max(enter,back)<1e-5,(enter,back)
        cycles=c.cycleCheck(all=True,list=True) or [];assert not [x for x in cycles if rig['namespace'] in x],cycles
        return dict(count=count,animated=animated,standard=standard,general=general,enter=enter,back=back,chest_held=held,hips_delta=delta)
    finally:
        if state:cleanup()


def verify_keys(layer=None,weight=1.0):
    try:
        rig=setup(animated=True);h=rig['controls']['hips'];reports=[]
        if layer:
            for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
            l=c.animLayer('_bodyDirectionLayer',override=layer=='override');c.animLayer(l,e=True,selected=True,preferred=True,weight=weight)
        times={n:set(c.keyframe(n,q=True,tc=True) or []) for n in c.ls(type='animCurve')}
        for frame,mode in ((10,1),(20,0)):
            c.currentTime(frame);c.rotate(9,-4,6,h,r=True,os=True)
            before=pose();body_direction.switch(h,mode,key=True)
            delta=error(before,pose());c.currentTime(frame+1);c.currentTime(frame);replay=error(before,pose())
            assert max(delta,replay)<1e-5,(delta,replay)
            reports.append(dict(frame=frame,error=delta,replay=replay))
        added=sorted({t for n in c.ls(type='animCurve') for t in set(c.keyframe(n,q=True,tc=True) or [])-times.get(n,set())})
        assert added==[10.0,20.0],added
        return dict(layer=layer,weight=weight,reports=reports,added_times=added)
    finally:
        if state:cleanup()


def verify_translation_precision():
    """Rotated, translated hips exercise float rounding in the body graph."""
    try:
        rig=setup();h=rig['controls']['hips'];ch=rig['controls']['chest']
        c.setAttr(h+'.translate',-16.4883141596,-3.7670298639,-16.5066641775)
        c.setAttr(h+'.rotate',5.5143107315,-36.2401402042,1.2081861839)
        c.setAttr(ch+'.rotate',-35.7258279084,-15.1147596064,-29.9644408605)
        baseline=pose();reports=[]
        for frame,mode in ((10,1),(20,0),(30,1),(40,0)):
            c.currentTime(frame)
            report=body_direction.switch(h,mode,key=True)
            c.currentTime(frame+1);c.currentTime(frame)
            report['replay_error']=error(baseline,pose())
            assert report['replay_error']<1e-5,report
            reports.append(report)
        assert sorted(set(c.keyframe(h+'.bodyDrive',q=True,tc=True)))==[10,20,30,40]
        return reports
    finally:
        if state:cleanup()


def setup_native(auto=True):
    """After idle, check_native(1); defer undo/redo and check 0/1, then cleanup."""
    import functools,maya.utils
    rig=setup(animated=True);c.currentTime(14);h=rig['controls']['hips']
    c.rotate(9,-4,6,h,r=True,os=True);state['native_pose']=pose()
    c.autoKeyframe(state=auto);arm_ik._sync_mode_cache()
    maya.utils.executeDeferred(functools.partial(c.setAttr,h+'.bodyDrive',1))


def check_native(mode):
    err=error(state['native_pose'],pose())
    assert c.getAttr(state['rig']['controls']['hips']+'.bodyDrive')==mode and err<1e-5,err
    return dict(mode=mode,error=err)


def verify_stretch_transition(count=4,standard=False):
    """A stretched held pose must not drift before, at, or after the switch.

    In particular the intermediate controls have NO keys before the switch.
    Revisit mode 0 later too: its first compensation must not leak backwards.
    """
    try:
        rig=setup(count=count,standard=standard);h=rig['controls']['hips'];ch=rig['controls']['chest']
        c.currentTime(0);c.setKeyframe(ch,at=['tx','ty','tz','rx','ry','rz'])
        c.currentTime(5);c.move(3,5,-4,ch,r=True,ws=True)
        c.setKeyframe(ch,at=['tx','ty','tz','rx','ry','rz']);c.setKeyframe(h,at=['tx','ty','tz','rx','ry','rz','bodyDrive'])
        samples={}
        for f in (0,2,4,5,5.1,5.25,5.5,5.75,5.9,5.999,6):
            c.currentTime(f);samples[f]=pose()
        c.currentTime(6);body_direction.switch(h,1,key=True)
        errors={}
        for f,p in samples.items():c.currentTime(f);errors[f]=error(p,pose())
        assert max(errors.values())<1e-5,errors
        c.currentTime(12);before=pose();body_direction.switch(h,0,key=True)
        assert error(before,pose())<1e-5
        for f,p in samples.items():c.currentTime(f);assert error(p,pose())<1e-5,(f,error(p,pose()))
        c.currentTime(15);before=pose();body_direction.switch(h,1,key=True)
        assert error(before,pose())<1e-5
        for f,p in samples.items():c.currentTime(f);assert error(p,pose())<1e-5,(f,error(p,pose()))
        times=sorted(set(c.keyframe(h+'.bodyDrive',q=True,tc=True)))
        assert times==[5,6,12,15],times
        cycles=c.cycleCheck(all=True,list=True) or [];assert not [x for x in cycles if rig['namespace'] in x],cycles
        return dict(count=count,standard=standard,max_error=max(errors.values()),mode_key_times=times,sampled_times=list(samples))
    finally:
        if state:cleanup()
