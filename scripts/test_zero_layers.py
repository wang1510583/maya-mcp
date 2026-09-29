"""Zero-based controls keep base animation under half-weight edit layers."""
import uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_edit,live_arm_manual,arm_ik


def verify():
    nodes=set(c.ls(long=True));time=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    selection=c.ls(sl=True,long=True) or [];context=c.currentCtx();rig=None
    flags={l:{a:c.animLayer(l,q=True,**{a:True}) for a in ('selected','preferred')} for l in c.ls(type='animLayer') or []}
    for l in flags:c.animLayer(l,e=True,selected=False,preferred=False)
    c.autoKeyframe(state=False)
    try:
        prefix='_zeroLayer_'+uuid.uuid4().hex[:6];_,parts=fixture(prefix,animated=True)
        parts={k:v for k,v in parts.items() if k in ('body','arm_L','leg_L')}
        for p in parts.values():p.update(live_alignment=True,space_wrist=True,space_foot=True,space_chest=True)
        c.currentTime(3);rig=build(parts,namespace=prefix,zero_controls=True)
        targets=[n for p in parts.values() for n in p['targets']]
        base={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        layer=c.animLayer(prefix+'_edit',weight=.5,selected=True,preferred=True)
        controls=[rig['parts'][k]['zero_controls'][role] for k,role in [('body','chest'),('arm_L','middle_fk'),('leg_L','foot')]]
        reports=[]
        for ctrl in controls:
            attrs=[ctrl+'.rotate'+a for a in 'XYZ']
            c.animLayer(layer,e=True,attribute=attrs)
            c.setKeyframe(ctrl,at=['rx','ry','rz'],animLayer=layer)
            c.select(ctrl,r=True);c.setToolTo('RotateSuperContext');c.autoKeyframe(state=True)
            live_edit.before_drag('test');c.setAttr(ctrl+'.rz',c.getAttr(ctrl+'.rz')+4)
            live_edit.update_drag(force=True);live_edit.after_drag('test')
            before={n:c.xform(n,q=True,ws=True,m=True) for n in targets}
            c.currentTime(4);c.currentTime(3)
            error=max(abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
            assert error<1e-5,(ctrl,error)
            reports.append(dict(control=ctrl,error=error))
        assert all((c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==v for n,v in base.items())
        return dict(weight=.5,base_preserved=True,reports=reports)
    finally:
        if live_edit._gesture:
            for e in reversed(live_edit._gesture['arm_gestures']):live_arm_manual.finish(e,cancel=True)
            live_edit.after_drag('test')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-nodes,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.select(selection,r=True) if selection else c.select(cl=True)
        for l,v in flags.items():c.animLayer(l,e=True,**v)
        c.setToolTo(context);c.autoKeyframe(state=auto);arm_ik.install()
