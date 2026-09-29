"""Only direct elbow gestures may alter the animator's pole Z channel."""
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_edit,live_arm_manual,arm_ik


def verify():
    before=set(c.ls(l=True));selected=c.ls(sl=True,l=True);time=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);context=c.currentCtx();rig=None
    flags={l:{a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')} for l in c.ls(type='animLayer')}
    for l in flags:c.animLayer(l,e=True,selected=False,preferred=False)
    c.autoKeyframe(state=False);reports=[]
    try:
        ns='_poleZ_'+uuid.uuid4().hex[:6];_,parts=fixture(ns,animated=False)
        parts={k:v for k,v in parts.items() if k.startswith('arm')}
        for p in parts.values():p.update(live_alignment=True,space_wrist=True)
        rig=build(parts,namespace=ns,zero_controls=True)
        for key,p in rig['parts'].items():
            pole=p['zero_controls']['pole_locator'];plug=pole+'.translateZ'
            for manual in (False,True):
                if manual:
                    c.select(pole);c.setToolTo('moveSuperContext')
                    live_edit.before_drag('pole-z-direct');c.setAttr(plug,c.getAttr(plug)+.4)
                    live_edit.update_drag(force=True);live_edit.after_drag('pole-z-direct')
                    assert abs(c.getAttr(plug))>.1
                    c.setKeyframe(plug)
                value=c.getAttr(plug);curve=c.connectionInfo(plug,sfd=True)
                keys=(c.keyframe(plug,q=True,tc=True),c.keyframe(plug,q=True,vc=True))
                c.autoKeyframe(state=True)
                for role in ('end_fk','middle_fk','shoulder_fk'):
                    control=p['zero_controls'][role]
                    c.setKeyframe(control)
                    for attr,context,amount in [('translateX','moveSuperContext',.2),('rotateZ','RotateSuperContext',8),('rotateX','RotateSuperContext',5)]:
                        c.select(control);c.setToolTo(context);live_edit.before_drag('pole-z-test')
                        c.setAttr(control+'.'+attr,c.getAttr(control+'.'+attr)+amount)
                        live_edit.update_drag(force=True)
                        held={j:c.xform(j,q=True,ws=True,m=True) for j in p['joints']}
                        live_edit.after_drag('pole-z-test')
                        assert abs(c.getAttr(plug)-value)<1e-9,(key,role,attr,c.getAttr(plug),value)
                        assert c.keyframe(plug,q=True,time=(c.currentTime(q=True),)*2,vc=True)==[value]
                        assert max(abs(a-b) for j,m in held.items() for a,b in zip(m,c.xform(j,q=True,ws=True,m=True)))<1e-5
                reports.append(dict(side=key,manual_z=manual,z=value,held_key=True))
                c.autoKeyframe(state=False)
            arm_ik.switch(p['root'],1,key=False)
            value=c.getAttr(plug);keys=(c.keyframe(plug,q=True,tc=True),c.keyframe(plug,q=True,vc=True))
            for role in ('end_fk','middle_fk','shoulder_fk'):
                control=p['zero_controls'][role];c.select(control);c.setToolTo('moveSuperContext')
                live_edit.before_drag('pole-z-ik');c.setAttr(control+'.tx',c.getAttr(control+'.tx')+.1)
                live_edit.update_drag(force=True);live_edit.after_drag('pole-z-ik')
                assert abs(c.getAttr(plug)-value)<1e-9
                assert (c.keyframe(plug,q=True,tc=True),c.keyframe(plug,q=True,vc=True))==keys
            reports.append(dict(side=key,ik=True,z=value,curve_unchanged=True))
            # New frame, animated/nonzero Z, both modes and every arm handle.
            c.autoKeyframe(state=False)
            c.cutKey(plug,clear=True)
            c.setKeyframe(plug,time=1,value=.4);c.setKeyframe(plug,time=40,value=1.2)
            curve=c.connectionInfo(plug,sfd=True).split('.')[0]
            samples={t:c.keyframe(curve,q=True,eval=True,time=(t,t))[0] for t in (1,4.5,11.5,20.5,35,40)}
            other=[p2['zero_controls']['pole_locator']+'.translateZ' for k2,p2 in rig['parts'].items() if k2!=key][0]
            other_keys=(c.keyframe(other,q=True,tc=True),c.keyframe(other,q=True,vc=True))
            for mode in (0,1):
                c.autoKeyframe(state=False);arm_ik.switch(p['root'],mode,key=False)
                for i,role in enumerate(('shoulder_fk','middle_fk','end_fk')):
                    frame=10+mode*10+i;c.currentTime(frame);value=c.getAttr(plug)
                    control=p['zero_controls'][role];c.select(control);c.setToolTo('RotateSuperContext')
                    c.autoKeyframe(state=True);live_edit.before_drag('held-key')
                    c.setAttr(control+'.rz',c.getAttr(control+'.rz')+3)
                    live_edit.update_drag(force=True);live_edit.after_drag('held-key')
                    assert abs(c.getAttr(plug)-value)<1e-8
                    assert abs(c.keyframe(plug,q=True,time=(frame,frame),vc=True)[0]-value)<1e-8
                    c.currentTime(frame+.25);c.currentTime(frame)
                    assert abs(c.getAttr(plug)-value)<1e-8
            assert all(abs(c.keyframe(curve,q=True,eval=True,time=(t,t))[0]-v)<1e-8 for t,v in samples.items())
            assert (c.keyframe(other,q=True,tc=True),c.keyframe(other,q=True,vc=True))==other_keys
            for enabled,drag,frame in ((True,False,30),(False,True,31)):
                c.currentTime(frame);c.autoKeyframe(state=enabled)
                live_edit.before_drag('no-key')
                if drag:
                    c.setAttr(control+'.rz',c.getAttr(control+'.rz')+2);live_edit.update_drag(force=True)
                live_edit.after_drag('no-key')
                assert not c.keyframe(plug,q=True,time=(frame,frame),tc=True)
            # A forced hold key joins the active half-weight layer; base stays intact.
            c.autoKeyframe(state=False);c.currentTime(32)
            base=(c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))
            layer=c.animLayer(ns+'_'+key+'_edit',weight=.5,selected=True,preferred=True)
            c.animLayer(layer,e=True,attribute=[control+'.rotate'+a for a in 'XYZ'])
            c.setKeyframe(control,at=['rx','ry','rz'],animLayer=layer)
            value=c.getAttr(plug);c.autoKeyframe(state=True)
            live_edit.before_drag('layer-hold');c.setAttr(control+'.rz',c.getAttr(control+'.rz')+3)
            live_edit.update_drag(force=True);live_edit.after_drag('layer-hold')
            layer_curve=c.animLayer(layer,q=True,findCurveForPlug=plug)
            assert layer_curve and c.keyframe(layer_curve,q=True,time=(32,32),tc=True)==[32.0]
            c.currentTime(33);c.currentTime(32)
            assert abs(c.getAttr(plug)-value)<1e-8
            assert (c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))==base
            c.animLayer(layer,e=True,selected=False,preferred=False)
            reports.append(dict(side=key,animated_hold=True,interpolation_preserved=True,other_side_preserved=True,no_op_and_auto_off=True,layer_weight=.5))
        return reports
    finally:
        if live_edit._gesture:
            for e in live_edit._gesture['arm_gestures']:live_arm_manual.finish(e,cancel=True)
            live_edit.after_drag('pole-z-cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(l=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        for l,v in flags.items():c.animLayer(l,e=True,**v)
        c.currentTime(time);c.select(selected) if selected else c.select(cl=True)
        c.setToolTo(context);c.autoKeyframe(state=auto);arm_ik.install()
