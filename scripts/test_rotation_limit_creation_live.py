"""Focused live regression; only disposable fixture nodes are edited."""
import importlib
import json
import runpy
import uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'outputs/rotation_limit_regression'
OUT.mkdir(parents=True,exist_ok=True)
helpers=runpy.run_path(str(BASE/'scripts/test_integrated_rig_live.py'))


def reload_changed():
    for name in ('rotation_limits','custom_body.targets','soft_limb.selection','soft_leg.selection',
                 'controller_shapes','integrated','integrated.builder'):
        importlib.reload(importlib.import_module('maya_agent.rigs.'+name))


def limits(node):
    for axis in 'XY':
        for bound in ('min','max'):
            c.setAttr(node+'.'+bound+'Rot'+axis+'Limit',0)
            c.setAttr(node+'.'+bound+'Rot'+axis+'LimitEnable',True)


def verify(animated=False,fail=False,drive=True,reverse_shoulders=False):
    from maya_agent.rigs.integrated import builder
    from maya_agent.rigs import rotation_limits as rl
    before=set(c.ls(long=True));sel=c.ls(sl=True,long=True);frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    prefix='_limitFix_'+uuid.uuid4().hex[:7];rig=None;old_constraint=c.parentConstraint
    try:
        root,parts=helpers['fixture'](prefix,animated=False,shoulders=True)
        if reverse_shoulders:
            for side in 'LR':
                nodes=parts['arm_'+side]['targets']
                matrices=[c.xform(n,q=True,ws=True,m=True) for n in nodes]
                c.setAttr(parts['shoulder_'+side]['targets'][0]+'.jointOrientZ',180)
                for n,m in zip(nodes,matrices):c.xform(n,ws=True,m=m)
        limbkeys=['arm_L','arm_R','leg_L','leg_R']
        targets=[parts[k]['targets'][1] for k in limbkeys]
        for n in targets:limits(n)
        if animated:
            for k in limbkeys:
                n=parts[k]['targets'][1]
                for f,v in [(1,0),(3,15),(5,-15)]:c.setKeyframe(n,at='rz',t=f,v=v)
            for p in parts.values():p['copy_animation']=True
        for p in parts.values():p['drive_targets']=drive
        c.currentTime(1)
        snapshot={n:rl.snapshot(n) for n in targets}
        if fail:
            def broken(*args,**kwargs):
                if kwargs.get('name')==prefix+':leg_R_target2':raise RuntimeError('injected late failure')
                return old_constraint(*args,**kwargs)
            c.parentConstraint=broken
        try:
            rig=builder.build(parts,namespace=prefix,create_master=False)
            assert not fail,'Failure was not injected'
        except RuntimeError as exc:
            if not fail or 'injected late failure' not in str(exc):raise
            assert all(rl.snapshot(n)==snapshot[n] for n in targets),'Limits not restored'
            return dict(passed=True,late_failure_restored=True,animated=animated)
        finally:c.parentConstraint=old_constraint
        if not drive:
            assert all(rl.snapshot(n)==snapshot[n] for n in targets)
            return dict(passed=True,undriven_limits_unchanged=True)
        for k,n in zip(limbkeys,targets):
            assert not any(rl.snapshot(n)[a] for a in rl.ENABLES)
            assert rig['parts'][k]['original_rotation_limits'][n]==snapshot[n]
        worst=0.;poses=0
        if not animated:
            for key in limbkeys:
                part=rig['parts'][key]
                control=part['controls']['shoulder_fk' if key.startswith('arm') else 'foot']
                for axis in 'XYZ':
                    plug=control+'.rotate'+axis;v=c.getAttr(plug)
                    for angle in (-181,-179,-91,-89,0,89,91,179,181):
                        c.setAttr(plug,v+angle);c.dgdirty(allPlugs=True)
                        for mapping in part['original_target_mapping']:
                            error=max(abs(a-b) for a,b in zip(c.xform(mapping['target'],q=True,ws=True,m=True),c.xform(mapping['driver'],q=True,ws=True,m=True)))
                            worst=max(worst,error);assert error<1e-5,(key,axis,angle,error)
                        poses+=1
                    c.setAttr(plug,v)
        for side in 'LR':
            key='shoulder_'+side;p=rig['parts'][key];s=p['appearance']['controls']['clavicle']['shapes'][0]
            pts=[c.xform(x,q=True,ws=True,t=True) for x in c.ls(s+'.cv[*]',fl=True)]
            centroid=om.MVector(*[sum(p[i] for p in pts)/len(pts) for i in range(3)])
            start=om.MVector(*c.xform(parts[key]['targets'][0],q=True,ws=True,t=True))
            end=om.MVector(*c.xform(parts['arm_'+side]['targets'][0],q=True,ws=True,t=True))
            assert (centroid-start)*(end-start)>0,(key,list(centroid))
        return dict(passed=True,animated=animated,max_build_error=rig['max_world_error'],sweep_poses=poses,max_sweep_error=worst,shoulders=True,reverse_shoulders=reverse_shoulders)
    finally:
        c.parentConstraint=old_constraint
        if rig:helpers['remove'](rig)
        new=set(c.ls(long=True))-before
        for n in new:
            if c.objExists(n) and c.objectType(n,isAType='constraint'):c.delete(n)
        for n in sorted(new,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before,'Fixture cleanup changed scene nodes'


def run():
    reload_changed()
    reports=[]
    for kwargs in ({},{'animated':True},{'fail':True},{'animated':True,'fail':True},{'drive':False},{'reverse_shoulders':True}):
        reports.append(verify(**kwargs))
    (OUT/'creation_regression.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    return reports
