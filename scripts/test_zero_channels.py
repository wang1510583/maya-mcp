"""Disposable full-character zero-channel, playback and interaction regressions."""
import uuid
import maya.cmds as c
from maya_agent.rigs import zero_channels,live_edit,live_arm_manual,switch_panel,arm_ik
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove


def verify(animated=False,live=True,manual=False):
    nodes=set(c.ls(long=True));time=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    selected=c.ls(sl=True,long=True) or [];context=c.currentCtx();rig=None
    layers={l:{a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')} for l in c.ls(type='animLayer') or []}
    for l in layers:c.animLayer(l,e=True,selected=False,preferred=False)
    base=c.animLayer(q=True,root=True)
    if base:c.animLayer(base,e=True,selected=True,preferred=True)
    c.autoKeyframe(state=False)
    try:
        prefix='_zeroTest_'+uuid.uuid4().hex[:6];_,parts=fixture(prefix,animated=animated,shoulders=True)
        for p in parts.values():p.update(live_alignment=live,space_head=True,space_chest=True,space_upper_arm=True,space_wrist=True,space_foot=True,space_knee=True)
        c.currentTime(3);rig=build(parts,namespace=prefix)
        targets=[n for p in parts.values() for n in p['targets']]
        def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in targets}
        def error(before):return max(abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        samples={}
        for f in (1,1.25,2,2.5,3,3.75,4,4.5,5):c.currentTime(f);samples[f]=pose()
        c.currentTime(3);data=zero_channels.build(rig)
        controls=[n for p in data['controls'].values() for n in p.values()]
        assert max(abs(c.getAttr(n+'.'+a)) for n in controls for a in zero_channels.TR)<1e-8
        import json
        from maya_agent.rigs.integrated import display
        layer=display.apply(rig)['layer']
        members=set(c.editDisplayLayerMembers(layer,q=True,fullNames=True) or [])
        for p in rig['parts'].values():
            for role,n in p['zero_controls'].items():
                if role in ('parameters','settings','end_locator','roll'):
                    assert c.ls(n,long=True)[0] in members,n
                    continue
                meta=json.loads(c.getAttr(n+'.zeroChannelData'))
                copies=c.listRelatives(n,s=True,f=True) or []
                assert len(copies)==len(meta['artwork_sources']),n
                for src,dst in zip(meta['artwork_sources'],copies):
                    assert c.getAttr(dst+'.lodVisibility'),dst
                    if c.nodeType(src)=='nurbsCurve':
                        original=c.xform(src+'.cv[*]',q=True,ws=True,t=True)
                        cloned=c.xform(dst+'.cv[*]',q=True,ws=True,t=True)
                        assert len(original)==len(cloned),(src,dst)
                        assert max(abs(a-b) for a,b in zip(original,cloned))<1e-5,(src,dst)
        errors=[]
        for f,before in samples.items():c.currentTime(f);errors.append(error(before))
        assert max(errors)<1e-5,errors
        c.currentTime(3);panel=switch_panel.build(rig['root'])
        switches=[]
        for frame,mode in ((10,1),(20,0)):
            c.currentTime(frame)
            for role,handle in panel['sliders'].items():
                before=pose();switch_panel.apply(handle,mode,key=True)
                delta=error(before);assert delta<1e-5,(role,delta)
                after=pose();c.currentTime(frame+1);c.currentTime(frame)
                replay=error(after);assert replay<1e-5,(role,'replay',replay)
                switches.append(dict(role=role,mode=mode,error=delta,replay=replay))
        for handle in panel['sliders'].values():
            d=switch_panel._read(handle,'spaceSliderData');c.currentTime(30);c.select(handle,r=True);c.setKeyframe()
            for plug in list(d['key_proxies'].values())+[d['plug']]:assert 30 in (c.keyframe(plug,q=True,tc=True) or []),plug
        drags=[];c.currentTime(30)
        for key,role in [('body','hips'),('body','chest'),('head','head'),('shoulder_L','clavicle'),('arm_L','shoulder_fk'),('arm_L','middle_fk'),('arm_L','end_fk'),('leg_L','foot'),('leg_L','toe_end'),('leg_L','knee')]:
            n=rig['parts'][key]['zero_controls'][role]
            for attr,context_name,amount in [('rotateZ','RotateSuperContext',3),('translateX','moveSuperContext',.1)]:
                if c.getAttr(n+'.'+attr,lock=True):continue
                c.select(n,r=True);c.setToolTo(context_name)
                before=pose();live_edit.before_drag('test');live_edit.after_drag('test')
                assert error(before)<1e-5,(key,role,'click')
                live_edit.before_drag('test');c.setAttr(n+'.'+attr,c.getAttr(n+'.'+attr)+amount)
                live_edit.update_drag(force=True);held=pose();live_edit.after_drag('test')
                delta=error(held);assert delta<1e-5,(key,role,'release',delta)
                drags.append(dict(part=key,role=role,attribute=attr,release_error=delta))
        cycles=[n for n in c.cycleCheck(all=True,list=True) or [] if prefix in n]
        assert not cycles,cycles
        manual_errors=[]
        if manual:
            import maya.mel as mel
            # Previous drag checks deliberately left unkeyed poses on other
            # parts. Record them before checking the manual alignment replay.
            c.setKeyframe(controls)
            n=rig['parts']['arm_L']['zero_controls']['end_fk'];c.select(n,r=True)
            before=pose()
            for _ in range(3):
                mel.eval('kurok_recalculate_system(0);');delta=error(before)
                assert delta<1e-5,('manual alignment',delta)
                manual_errors.append(delta)
            after=pose();c.currentTime(31);c.currentTime(30);assert error(after)<1e-5
        return dict(animated=animated,live=live,controls=len(controls),motion_error=max(errors),switches=switches,drags=drags,manual_errors=manual_errors)
    finally:
        if live_edit._gesture:
            for e in reversed(live_edit._gesture['arm_gestures']):live_arm_manual.finish(e,cancel=True)
            live_edit.after_drag('test')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-nodes,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.select(selected,r=True) if selected else c.select(cl=True)
        for l,flags in layers.items():c.animLayer(l,e=True,**flags)
        c.setToolTo(context);c.autoKeyframe(state=auto);arm_ik.install()
