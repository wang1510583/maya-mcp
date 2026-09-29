"""Disposable full-character panel regression in the running Maya scene."""
import json
import uuid
import maya.cmds as c
from maya_agent.rigs import switch_panel,arm_ik
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove


def verify():
    initial=set(c.ls(long=True));time=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True);selection=c.ls(sl=True,long=True) or []
    rig=None;c.autoKeyframe(state=False)
    layers={l:{a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')} for l in c.ls(type='animLayer') or []}
    for l in layers:c.animLayer(l,e=True,selected=False,preferred=False)
    base=c.animLayer(q=True,root=True)
    if base:c.animLayer(base,e=True,selected=True,preferred=True)
    try:
        prefix='_switchPanelTest_'+uuid.uuid4().hex[:6];_,parts=fixture(prefix,shoulders=True)
        for part in parts.values():
            part.update(copy_animation=False,live_alignment=True,space_head=True,space_chest=True,space_upper_arm=True,space_wrist=True,space_foot=True,space_knee=True)
        rig=build(parts,namespace=prefix);panel=switch_panel.build(rig['root'])
        assert len(panel['sliders'])==10 and not panel['missing'],panel
        assert panel['column_order']==['R','L'] and panel['master_control']==panel['root']
        assert switch_panel.build(rig['root'])['root']==panel['root']
        nodes=list(dict.fromkeys(n for p in rig['parts'].values() for n in p.get('joints',[])))+[n for p in parts.values() for n in p['targets']]
        def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
        def error(a):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,c.xform(n,q=True,ws=True,m=True)))
        c.currentTime(1)
        for handle in panel['sliders'].values():c.setKeyframe(switch_panel._read(handle,'spaceSliderData')['plug'])
        reports=[]
        for f,mode in ((10,1),(20,0)):
            c.currentTime(f)
            for role,handle in panel['sliders'].items():
                before=pose();switch_panel.apply(handle,mode,key=True);delta=error(before);assert delta<1e-5,(role,f,delta)
                d=switch_panel._read(handle,'spaceSliderData');assert abs(c.getAttr(d['display']+'.tx')-mode*d['travel'])<1e-8
                assert c.getAttr(handle+'.tx')==0 and not c.listConnections(handle+'.tx',s=True,d=False)
                reports.append(dict(role=role,frame=f,error=delta))
            before=pose();c.currentTime(f+1);c.currentTime(f);assert error(before)<1e-5
        for f,mode in ((1,0),(9.5,0),(10,1),(19.5,1),(20,0)):
            c.currentTime(f)
            for handle in panel['sliders'].values():
                d=switch_panel._read(handle,'spaceSliderData')
                assert c.getAttr(d['plug'])==mode
                assert abs(c.getAttr(d['display']+'.tx')-mode*d['travel'])<1e-8
                assert c.keyframe(d['plug'],q=True,tc=True)==[1.,10.,20.]
        keyed=[];c.currentTime(30)
        for role,handle in panel['sliders'].items():
            d=switch_panel._read(handle,'spaceSliderData');c.select(handle,r=True);before=pose()
            c.setKeyframe()  # Native selection-based S behavior, no helper command.
            assert error(before)<1e-5
            for source in list(d['key_proxies'].values())+[d['plug']]:
                assert 30. in (c.keyframe(source,q=True,tc=True) or []),(role,source)
            assert not c.listConnections(handle+'.tx',s=True,d=False)
            keyed.append(dict(role=role,attributes=len(d['key_proxies'])+1))
        cycles=c.cycleCheck(all=True,list=True) or [];assert not [x for x in cycles if prefix in x],cycles
        return dict(sliders=10,reports=reports,mode_key_times=[1,10,20,30],playback_samples=[1,9.5,10,19.5,20],selection_keying=keyed,cycles=False)
    finally:
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-initial,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time)
        for l,flags in layers.items():c.animLayer(l,e=True,**flags)
        c.select(selection,r=True) if selection else c.select(cl=True)
        c.autoKeyframe(state=auto);arm_ik.install()
