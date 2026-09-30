"""A shared elbow and FK handle must prepare their arm only once."""
import uuid
import maya.cmds as c
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_edit,live_arm_manual,arm_ik
from scripts.test_integrated_rig_live import fixture,remove


def verify(layer=False):
    nodes=set(c.ls(long=True));selected=c.ls(sl=True,long=True) or []
    time=c.currentTime(q=True);context=c.currentCtx();auto=c.autoKeyframe(q=True,state=True)
    flags={l:{a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')} for l in c.ls(type='animLayer') or []}
    rig=None;cases=0
    try:
        for l in flags:c.animLayer(l,e=True,selected=False,preferred=False)
        c.autoKeyframe(state=False);prefix='_poleMulti_'+uuid.uuid4().hex[:6]
        _,parts=fixture(prefix,animated=True)
        parts={k:v for k,v in parts.items() if k.startswith('arm')}
        for p in parts.values():p.update(live_alignment=True,space_wrist=True)
        c.currentTime(3);rig=build(parts,namespace=prefix,zero_controls=True)
        if layer:
            edit=c.animLayer(prefix+'_edit',weight=.5,selected=True,preferred=True)
            for p in rig['parts'].values():
                attrs=[n+'.'+a for n in p['zero_controls'].values() for a in live_edit.TR if not c.getAttr(n+'.'+a,lock=True)]
                c.animLayer(edit,e=True,attribute=attrs)
                c.setKeyframe(attrs,animLayer=edit)
        joints=[n for p in rig['parts'].values() for n in p['joints']]
        def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in joints}
        def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))
        for side in ('arm_L','arm_R','both'):
            active=list(rig['parts'].values()) if side=='both' else [rig['parts'][side]]
            for role in ('shoulder_fk','middle_fk','end_fk'):
                chosen=[p['zero_controls'][r] for p in active for r in (role,'pole_locator')]
                for reverse in (False,True):
                    c.select(list(reversed(chosen)) if reverse else chosen)
                    assert len(live_edit._roots())==len(active)
                    for rotate in (False,True):
                        c.setToolTo('RotateSuperContext' if rotate else 'moveSuperContext')
                        before=pose();curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
                        c.autoKeyframe(state=True);live_edit.before_drag('mixed-noop');live_edit.after_drag('mixed-noop')
                        assert error(before,pose())<1e-5
                        assert all((c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==v for n,v in curves.items())
                        live_edit.before_drag('mixed-drag')
                        for n in chosen:
                            a='rotateZ' if rotate and not c.getAttr(n+'.rotateZ',lock=True) else 'translateZ'
                            c.setAttr(n+'.'+a,c.getAttr(n+'.'+a)+(.2 if a.startswith('translate') else 2))
                        live_edit.update_drag(force=True);moved=pose();live_edit.after_drag('mixed-drag')
                        assert error(moved,pose())<1e-5
                        expected=pose();c.currentTime(4);c.currentTime(3)
                        assert error(expected,pose())<1e-5
                        cases+=1
        return dict(cases=cases,half_weight_layer=layer,noop_unchanged=True,replay_and_release_stable=True)
    finally:
        if live_edit._gesture:
            for e in live_edit._gesture['arm_gestures']:live_arm_manual.finish(e,cancel=True)
            live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-nodes,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        for l,v in flags.items():c.animLayer(l,e=True,**v)
        c.currentTime(time);c.select(selected,r=True) if selected else c.select(cl=True)
        c.setToolTo(context);c.autoKeyframe(state=auto);arm_ik.install()
