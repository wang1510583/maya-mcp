"""A rejected rebase must preserve completed motion, keys and all relays."""
import uuid
import maya.cmds as c
from maya_agent.rigs import live_edit,live_arm_manual,live_alignment
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove


def verify():
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();rig=None;reports=[]
    original=live_edit._apply_plan
    try:
        c.autoKeyframe(state=False);prefix='_alignmentFallback_'+uuid.uuid4().hex[:6]
        _,parts=fixture(prefix,False)
        rig=build({k:v for k,v in parts.items() if k.startswith('arm')},namespace=prefix)
        for key,p in rig['parts'].items():
            d=live_alignment.enable(p,'arm');controls=d['controls'];proxy=controls['end_fk']
            def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
            def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))
            def reject(*args,**kwargs):
                original(*args,**kwargs)
                plug=controls['shoulder_fk']+'.rotateZ'
                c.setAttr(plug,c.getAttr(plug)+37)
            nodes=list(controls.values())+[p['namespace']+':elb_'+p['side']+'1',p['namespace']+':hand_'+p['side']+'1']
            baseline=live_edit._snapshot([n+'.'+a for n in nodes for a in live_edit.TR])
            natural_rejections=0
            for delta in ((-15,0,0),(20,0,0),(0,30,0),(0,0,30),(-6,6,1)):
                live_edit._restore(baseline)
                c.move(*delta,proxy,r=True,ws=True);held=pose()
                saved=live_edit._snapshot(baseline[0])
                try:live_edit.prepare(p['root'])
                except live_edit.PosePreservationError:
                    natural_rejections+=1
                    assert live_edit._snapshot(saved[0])==saved
                assert error(held,pose())<1e-5,'Reach stress changed the pose'
            live_edit._restore(baseline)
            for n in nodes:c.setKeyframe(n,at=list(live_edit.TR),time=0)
            c.currentTime(7);c.autoKeyframe(state=True)
            c.select(proxy);c.setToolTo('moveSuperContext')
            start=pose();live_edit.before_drag('test')
            c.move(-.3,.2,.15,proxy,r=True,ws=True);live_edit.update_drag();desired=pose()
            entry=live_edit._gesture['arm_gestures'][0]
            live_edit._apply_plan=reject
            try:live_edit.after_drag('test')
            finally:live_edit._apply_plan=original
            assert entry.get('alignment_fallback'),'Fault was not exercised'
            assert error(start,desired)>.01
            assert error(desired,pose())<1e-5,'Failed rebase reverted the drag'
            c.currentTime(8);c.currentTime(7)
            assert error(desired,pose())<1e-5,'Fallback did not key the accepted pose'
            assert c.autoKeyframe(q=True,state=True) and not live_edit._gesture
            for src,dst in entry['edges']:assert c.isConnected(src,dst)
            assert c.isConnected(entry['display_edge'],proxy+'.offsetParentMatrix')
            # A refused mouse-down rebase also permits edits without snapping.
            live_edit._apply_plan=reject
            try:
                before_click=live_edit._snapshot(entry['snapshot'][0]);held=pose()
                live_edit.before_drag('test');live_edit.after_drag('test')
                assert error(held,pose())<1e-5
                assert live_edit._snapshot(before_click[0])==before_click,'No-op changed curves'
                live_edit.before_drag('test')
                assert error(held,pose())<1e-5,'Fallback mouse-down snapped'
                c.move(.12,-.08,.03,proxy,r=True,ws=True);live_edit.update_drag();desired=pose()
                live_edit.after_drag('test')
                assert error(held,desired)>.01
                assert error(desired,pose())<1e-5
                c.currentTime(8);c.currentTime(7)
                assert error(desired,pose())<1e-5
            finally:live_edit._apply_plan=original
            # Unrelated failures must still propagate, not be misclassified.
            def unexpected(*args,**kwargs):raise ValueError('injected external driver error')
            live_edit._apply_plan=unexpected
            try:
                try:live_edit.before_drag('test')
                except ValueError as exc:assert str(exc)=='injected external driver error'
                else:raise AssertionError('Unexpected error was swallowed')
            finally:live_edit._apply_plan=original
            assert not live_edit._gesture and c.autoKeyframe(q=True,state=True)
            reports.append(dict(side=p['side'],finish_pose_error=error(desired,pose()),keys_preserved=True,connections_restored=True,natural_rejections=natural_rejections))
            c.autoKeyframe(state=False)
        return reports
    finally:
        live_edit._apply_plan=original
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(sel,r=True) if sel else c.select(cl=True)
