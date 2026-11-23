"""Recover interrupted gestures on disposable limbs without replacing the scene."""
import importlib
import json
from pathlib import Path
import runpy
import uuid
import maya.cmds as c


def run():
    from maya_agent.rigs import input_recovery,live_edit,zero_channels
    from maya_agent.rigs.integrated import builder
    for m in (input_recovery,zero_channels,live_edit):importlib.reload(m)
    helper=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));sel=c.ls(sl=True,long=True);frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);ctx=c.currentCtx();rig=None;original=c.connectAttr
    reports=[]
    def pose(nodes):return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def error(old):return max(abs(a-b) for n,m in old.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
    def keys(ctrl):return {a:[c.keyframe(ctrl+'.'+a,q=True,tc=True),c.keyframe(ctrl+'.'+a,q=True,vc=True)] for a in zero_channels.TR}
    try:
        c.autoKeyframe(state=False)
        prefix='_recovery_'+uuid.uuid4().hex[:7]
        fixture,parts=helper['fixture'](prefix)
        parts={k:v for k,v in parts.items() if k in ('leg_L','leg_R')}
        for opt in parts.values():opt['live_alignment']=True
        rig=builder.build(parts,namespace=prefix,zero_controls=True,create_master=False)
        for key,part in rig['parts'].items():
            ctrl=part['zero_controls']['foot'];live=part['live_controls']['foot'];source=part['controls']['foot']
            for a in zero_channels.TR:
                v=c.getAttr(ctrl+'.'+a)
                for f,d in ((1,0),(4,.2),(9.5,-.1)):c.setKeyframe(ctrl,at=a,t=f,v=v+d)
            c.currentTime(4);curves=keys(ctrl)
            for a in zero_channels.TR:
                value=c.getAttr(source+'.'+a);c.disconnectAttr(live+'.'+a,source+'.'+a);c.setAttr(source+'.'+a,value)
            c.setAttr(source+'.ty',c.getAttr(source+'.ty')+.4)
            c.setAttr(source+'.rx',c.getAttr(source+'.rx')+7)
            c.dgdirty(allPlugs=True);c.refresh(force=True)
            baseline=pose(part['joints']+[ctrl,source]);raw=c.getAttr(ctrl+'.zeroChannelData')
            # A failed final reconnection must restore the exact disconnected pose.
            def fail(src,dst,**kw):
                if dst==source+'.rotateZ':raise RuntimeError('injected recovery failure')
                return original(src,dst,**kw)
            c.connectAttr=fail
            try:input_recovery.repair(ctrl)
            except RuntimeError as exc:assert 'injected recovery failure' in str(exc),str(exc)
            else:raise AssertionError('Failure injection did not run')
            finally:c.connectAttr=original
            assert c.getAttr(ctrl+'.zeroChannelData')==raw
            assert all(not c.connectionInfo(source+'.'+a,sfd=True) for a in zero_channels.TR)
            assert error(baseline)<1e-5 and keys(ctrl)==curves
            # Actual callback path restores connections before isolating the drag.
            c.select(ctrl,r=True);c.setToolTo('moveSuperContext')
            live_edit.before_drag('recovery-regression');live_edit.after_drag('recovery-regression')
            assert all(c.isConnected(live+'.'+a,source+'.'+a) for a in zero_channels.TR)
            assert error(baseline)<1e-5 and keys(ctrl)==curves
            assert input_recovery.repair(ctrl) is None
            reports.append(dict(side=key,automatic_recovery=True,rollback=True,sparse_keys_unchanged=True,pose_error=error(baseline)))
            # A registered input replaced by another driver is never overwritten.
            c.disconnectAttr(live+'.translateX',source+'.translateX')
            c.disconnectAttr(live+'.translateY',source+'.translateY')
            external=c.createNode('addDoubleLinear',name=prefix+'_external')
            c.setAttr(external+'.input1',c.getAttr(source+'.translateY'))
            c.connectAttr(external+'.output',source+'.translateY')
            old=c.getAttr(ctrl+'.zeroChannelData')
            try:input_recovery.repair(ctrl)
            except ValueError as exc:assert '其他驱动' in str(exc),str(exc)
            else:raise AssertionError('External driver was not rejected')
            assert c.getAttr(ctrl+'.zeroChannelData')==old
            assert c.isConnected(external+'.output',source+'.translateY')
            assert not c.connectionInfo(source+'.translateX',sfd=True)
            c.disconnectAttr(external+'.output',source+'.translateY');c.delete(external)
            for a in ('translateX','translateY'):c.connectAttr(live+'.'+a,source+'.'+a)
            # A disconnected last channel is rejected before earlier ones change.
            c.disconnectAttr(live+'.rotateZ',source+'.rotateZ')
            try:zero_channels.begin(ctrl)
            except ValueError as exc:assert '内部输入连接已断开' in str(exc)
            else:raise AssertionError('Missing channel not rejected')
            assert all(c.isConnected(live+'.'+a,source+'.'+a) for a in zero_channels.TR[:-1])
            c.connectAttr(live+'.rotateZ',source+'.rotateZ')
            reports[-1].update(external_driver_preserved=True,late_missing_preflight=True)
        return dict(passed=True,cases=reports)
    finally:
        c.connectAttr=original
        if live_edit._gesture:live_edit.after_drag('recovery-regression')
        if rig:helper['remove'](rig)
        new=set(c.ls(long=True))-before
        for n in new:
            if c.objExists(n) and c.objectType(n,isAType='constraint'):c.delete(n)
        for n in sorted(new,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.setToolTo(ctx)
        c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
