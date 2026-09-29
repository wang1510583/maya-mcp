"""Matched head and bilateral knee spaces on disposable integrated rigs."""
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import head_knee_space,arm_ik

state=None


def setup(animated=True,live=True):
    global state
    state=dict(nodes=set(c.ls(long=True)),time=c.currentTime(q=True),selection=c.ls(sl=True,long=True) or [],auto=c.autoKeyframe(q=True,state=True),layers={},rig=None)
    for l in c.ls(type='animLayer') or []:
        state['layers'][l]={a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')}
        c.animLayer(l,e=True,selected=False,preferred=False)
    base=c.animLayer(q=True,root=True)
    if base:c.animLayer(base,e=True,selected=True,preferred=True)
    c.autoKeyframe(state=False);prefix='_headKneeTest_'+uuid.uuid4().hex[:7]
    _,parts=fixture(prefix,animated);parts['head']['space_head']=True
    for key in ('leg_L','leg_R'):parts[key].update(space_foot=True,space_knee=True,live_alignment=live)
    c.currentTime(3 if animated else 1)
    state['rig']=build({k:p for k,p in parts.items() if k in ('body','head','leg_L','leg_R')},namespace=prefix)
    state['controls']=[p['controls']['head' if k=='head' else 'knee'] for k,p in state['rig']['parts'].items() if k=='head' or k.startswith('leg')]


def pose(control):
    return {n:c.xform(n,q=True,ws=True,m=True) for n in head_knee_space._data(control)['joints']}


def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))


def verify(animated=True,live=True,layer=None,weight=1.0):
    try:
        setup(animated,live);reports=[]
        if layer:
            for l in c.ls(type='animLayer'):c.animLayer(l,e=True,selected=False,preferred=False)
            l=c.animLayer('_headKneeLayer',override=layer=='override');c.animLayer(l,e=True,selected=True,preferred=True,weight=weight)
        for control in state['controls']:
            data=head_knee_space._data(control);driver=data['driver']
            if data['role']=='knee':
                part=next(p for p in state['rig']['parts'].values() if p['root']==data['root'])
                driver=part.get('live_controls',{}).get('foot',driver)
            for frame,mode in ((10,1),(20,0)):
                c.currentTime(frame)
                c.rotate(9,-7,5,driver,r=True,os=True)
                c.move(.2,-.1,.15,driver,r=True,ws=True)
                # Keep explicit fixture driver edits for playback checks.
                c.setKeyframe(driver,at=['tx','ty','tz','rx','ry','rz'])
                before=pose(control);times={n:set(c.keyframe(n,q=True,tc=True) or []) for n in c.ls(type='animCurve')}
                response=head_knee_space.switch(control,mode,key=True)
                delta=error(before,pose(control));assert delta<1e-5,('switch',control,frame,delta)
                added={t for n in c.ls(type='animCurve') for t in set(c.keyframe(n,q=True,tc=True) or [])-times.get(n,set())}
                assert added.issubset({float(frame)}),(control,added)
                c.currentTime(frame+1);c.currentTime(frame);replay=error(before,pose(control));assert replay<1e-5,('replay',control,frame,replay)
                reports.append(dict(control=control,frame=frame,error=delta,replay=replay))
        return dict(animated=animated,live=live,layer=layer,weight=weight,reports=reports)
    finally:
        if state:cleanup()


def cleanup():
    global state
    c.autoKeyframe(state=False)
    if state['rig']:remove(state['rig'])
    for n in sorted(set(c.ls(long=True))-state['nodes'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    c.currentTime(state['time'])
    for l,flags in state['layers'].items():c.animLayer(l,e=True,**flags)
    c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    c.autoKeyframe(state=state['auto']);arm_ik.install();state=None
