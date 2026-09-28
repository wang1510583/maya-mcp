"""Live move/rotate edits must be represented by visible FK rotation keys."""
import math,uuid
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_alignment,live_edit


def verify():
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();rig=None;report=[]
    try:
        c.autoKeyframe(state=False);prefix='_fixedArm_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,False)
        rig=build({k:p for k,p in parts.items() if k.startswith('arm')},namespace=prefix)
        for key,p in rig['parts'].items():
            data=live_alignment.enable(p,'arm');ctrl=data['controls'];inputs=data['inputs']
            fixed={n:c.getAttr(n+'.translate')[0] for r in ('middle_fk','end_fk') for n in (ctrl[r],inputs[r])}
            def assert_fixed():
                for n,t in fixed.items():assert max(abs(a-b) for a,b in zip(t,c.getAttr(n+'.translate')[0]))<1e-8,(n,t,c.getAttr(n+'.translate'))
            # Reproduce a solved elbow which no longer coincides with its
            # hidden FK input. A tiny edit must not snap between those points.
            baseline=live_edit._snapshot([n+'.'+a for n in ctrl.values() for a in live_edit.TR])
            c.setAttr(ctrl['middle_fk']+'.rotate',17,-13,-70)
            gap=math.dist(c.xform(inputs['middle_fk'],q=True,ws=True,t=True),
                          c.xform(ctrl['middle_fk'],q=True,ws=True,t=True))
            assert gap>.01,('fixture must exercise a misaligned input',gap)
            twisted=live_edit._snapshot([n+'.'+a for n in ctrl.values() for a in live_edit.TR])
            nodes=list(ctrl.values())+list(data['targets'].values())
            def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
            def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))
            discontinuity=0
            for mode in ('move','rotate'):
                for amount in (0,.0001,.01):
                    live_edit._restore(twisted)
                    c.select(ctrl['middle_fk']);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
                    initial=pose();elbow_start=c.xform(ctrl['middle_fk'],q=True,ws=True,t=True)
                    live_edit.before_drag('misaligned-input')
                    discontinuity=max(discontinuity,error(initial,pose()))
                    if mode=='move':c.move(amount,amount/2,0,ctrl['middle_fk'],r=True,ws=True)
                    else:c.rotate(0,0,amount,ctrl['middle_fk'],r=True,os=True)
                    live_edit.update_drag(force=True);during=pose()
                    live_edit.after_drag('misaligned-input')
                    discontinuity=max(discontinuity,error(during,pose()))
                    assert error(initial,pose())<max(1e-6,amount*10),(mode,amount,error(initial,pose()))
                    if mode=='rotate':
                        assert math.dist(elbow_start,c.xform(ctrl['middle_fk'],q=True,ws=True,t=True))<1e-5
                    assert_fixed()
            assert discontinuity<1e-5,discontinuity
            live_edit._restore(baseline)
            c.select(ctrl['end_fk']);c.setToolTo('moveSuperContext')
            start=c.xform(ctrl['end_fk'],q=True,ws=True,t=True)
            delta=[-.4 if p['side']=='L' else .4,.3,.2]
            target=[a+b for a,b in zip(start,delta)]
            live_edit.before_drag('test');c.move(*delta,ctrl['end_fk'],r=True,ws=True)
            live_edit.update_drag()
            moving=math.dist(target,c.xform(p['joints'][2],q=True,ws=True,t=True))
            live_edit.after_drag('test');assert_fixed()
            assert moving<1e-5,('wrist drag target',p['side'],moving,target,c.xform(p['joints'][2],q=True,ws=True,t=True))
            elbow=c.xform(p['joints'][1],q=True,ws=True,t=True)
            c.setToolTo('RotateSuperContext')
            live_edit.before_drag('test');c.rotate(8,-11,5,ctrl['end_fk'],r=True,os=True);live_edit.after_drag('test')
            assert_fixed();wrist_hold=math.dist(elbow,c.xform(p['joints'][1],q=True,ws=True,t=True))
            assert wrist_hold<1e-5,wrist_hold
            c.select(ctrl['middle_fk'])
            for t in (6,8,12):
                for n in ctrl.values():c.setKeyframe(n,at=['rx','ry','rz'],time=t)
            c.autoKeyframe(state=True)
            for t,angle in ((6,12),(8,-16),(12,21),(8,9)):
                c.currentTime(t);live_edit.before_drag('test')
                c.rotate(0,0,angle,ctrl['middle_fk'],r=True,os=True);live_edit.update_drag();live_edit.after_drag('test')
                assert_fixed()
            bend_hold=0
            for i in range(25):
                c.currentTime(6+i*.25)
                bend_hold=max(bend_hold,math.dist(elbow,c.xform(p['joints'][1],q=True,ws=True,t=True)))
                assert_fixed()
            assert bend_hold<1e-5,('bend elbow hold',p['side'],bend_hold)
            c.currentTime(8);c.select(ctrl['end_fk']);c.setToolTo('moveSuperContext')
            live_edit.before_drag('test');c.move(*delta,ctrl['end_fk'],r=True,ws=True);live_edit.after_drag('test')
            assert_fixed()
            for r in ('middle_fk','end_fk'):
                assert not c.keyframe(ctrl[r],at=['tx','ty','tz'],q=True,tc=True),'Child translation was keyed'
            c.autoKeyframe(state=False);c.cutKey(list(ctrl.values()),clear=True)
            matrices={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']};residual=0
            for t in (0,6,7.5,8,9.5,12,20):
                c.currentTime(t)
                residual=max(residual,max(abs(a-b) for n,m in matrices.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
            assert residual<1e-5,residual
            c.select(ctrl['middle_fk']);c.setToolTo('moveSuperContext')
            lower_rot={ctrl[r]:c.getAttr(ctrl[r]+'.rotate')[0] for r in ('middle_fk','end_fk')}
            shoulder_before=c.xform(p['joints'][0],q=True,ws=True,t=True)
            elbow_before=c.xform(p['joints'][1],q=True,ws=True,t=True)
            live_edit.before_drag('test');c.move(0,.5,.3,ctrl['middle_fk'],r=True,ws=True);live_edit.after_drag('test')
            assert_fixed()
            assert math.dist(shoulder_before,c.xform(p['joints'][0],q=True,ws=True,t=True))<1e-5
            assert math.dist(elbow_before,c.xform(p['joints'][1],q=True,ws=True,t=True))>1e-4
            for n,v in lower_rot.items():assert max(abs(a-b) for a,b in zip(v,c.getAttr(n+'.rotate')[0]))<1e-8
            assert not c.ls(p['namespace']+':rotation_*')
            report.append(dict(side=p['side'],move_error=moving,wrist_rotation_elbow_error=wrist_hold,
                               multi_key_elbow_error=bend_hold,after_delete_motion=residual,child_translation_keys=0,
                               misaligned_input_gap=gap,boundary_error=discontinuity))
        return report
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(sel,r=True) if sel else c.select(cl=True)
