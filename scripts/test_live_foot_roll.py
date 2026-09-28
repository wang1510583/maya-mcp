"""Heel and toe-end must track the same foot, with correct editable pivots."""
import math
import uuid
import maya.cmds as c
import maya.api.OpenMaya as om
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_alignment,live_edit


def verify(animated=False):
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);rig=None;out=[]
    try:
        c.autoKeyframe(state=False)
        prefix='_footRollTest_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,animated)
        for p in parts.values():p.update(space_foot=True,space_knee=True)
        c.currentTime(3 if animated else 1)
        rig=build({k:v for k,v in parts.items() if k.startswith('leg')},namespace=prefix)
        for key,part in rig['parts'].items():
            data=live_alignment.enable(part,'leg');errors=[]
            c.setAttr(part['controls']['knee']+'.global',1)
            c.setAttr(part['live_controls']['foot']+'.global',1)
            for role in ('toe_end','heel')*3:
                ctrl=data['controls'][role];other=data['controls']['heel' if role=='toe_end' else 'toe_end']
                pose={n:c.xform(n,q=True,ws=True,m=True) for n in part['joints']}
                live_edit.prepare(part['root'])
                assert max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-5
                basis=om.MMatrix(c.xform(ctrl,q=True,ws=True,m=True))
                point=c.xform(other,q=True,ws=True,t=True)
                pivot=c.xform(ctrl,q=True,ws=True,t=True)
                rotation=om.MEulerRotation(math.radians(-7),0,0).asMatrix()
                expected=om.MPoint(point)*(basis.inverse()*rotation*basis)
                c.rotate(-7,0,0,ctrl,r=True,os=True)
                error=math.dist(list(expected)[:3],c.xform(other,q=True,ws=True,t=True))
                assert error<1e-5,(key,role,'other handle',error)
                assert math.dist(pivot,c.xform(ctrl,q=True,ws=True,t=True))<1e-5
                assert math.dist(point,c.xform(other,q=True,ws=True,t=True))>.01
                live_edit.prepare(part['root'])
                point=c.xform(other,q=True,ws=True,t=True)
                c.move(.04,.13,-.03,ctrl,r=True,ws=True)
                move_error=math.dist([a+b for a,b in zip(point,(.04,.13,-.03))],c.xform(other,q=True,ws=True,t=True))
                assert move_error<1e-5,(key,role,'move',move_error)
                errors.extend((error,move_error))
            out.append(dict(part=key,animated=animated,alternating_gestures=12,max_pivot_error=max(errors)))
        return out
    finally:
        if rig:remove(rig)
        for node in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(node):c.delete(node)
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(cl=True)


def verify_toe(animated=False):
    """Ball motion follows into toe position without imposing ball rotation."""
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);rig=None;out=[]
    try:
        c.autoKeyframe(state=False)
        prefix='_toeFollowTest_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,animated)
        c.currentTime(3 if animated else 1)
        rig=build({k:v for k,v in parts.items() if k.startswith('leg')},namespace=prefix)
        for key,p in rig['parts'].items():
            d=live_alignment.enable(p,'leg');ball=d['controls']['ball'];toe=d['controls']['toe'];errors=[]
            for angles in ((11,0,0),(0,-9,0),(0,0,13)):
                live_edit.prepare(p['root'])
                basis=om.MMatrix(c.xform(ball,q=True,ws=True,m=True))
                point=c.xform(toe,q=True,ws=True,t=True)
                # X/Y retain toe orientation; Z also drives the template's toe
                # group. All axes must still match the intended position graph.
                if angles[2]==0:
                    expected=om.MPoint(point)*basis.inverse()*om.MEulerRotation(*[math.radians(a) for a in angles]).asMatrix()*basis
                c.rotate(*angles,ball,r=True,os=True)
                if angles[2]==0:
                    error=math.dist(list(expected)[:3],c.xform(toe,q=True,ws=True,t=True));errors.append(error)
                    assert error<1e-5,(key,'ball rotation',error)
                visible=c.xform(toe,q=True,ws=True,m=True)
                pose={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
                live_edit.prepare(p['root'])
                error=max(abs(a-b) for a,b in zip(visible,c.xform(toe,q=True,ws=True,m=True)))
                assert error<1e-5,(key,'switch to toe',error)
                assert max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-5
                origin=c.xform(toe,q=True,ws=True,t=True)
                c.rotate(6,0,0,toe,r=True,os=True)
                assert math.dist(origin,c.xform(toe,q=True,ws=True,t=True))<1e-5
                # Toe rotation must drive the toe joint, not just the artwork.
                assert max(abs(a-b) for a,b in zip(pose[p['joints'][3]][:12],c.xform(p['joints'][3],q=True,ws=True,m=True)[:12]))>.001
                live_edit.prepare(p['root'])
                point=c.xform(toe,q=True,ws=True,t=True)
                c.move(.12,-.07,.09,ball,r=True,ws=True)
                error=math.dist([a+b for a,b in zip(point,(.12,-.07,.09))],c.xform(toe,q=True,ws=True,t=True))
                assert error<1e-5,(key,'ball translation',error);errors.append(error)
            out.append(dict(part=key,animated=animated,follow_error=max(errors),toe_edit=True,pose_preserved=True))
        return out
    finally:
        if rig:remove(rig)
        for node in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(node):c.delete(node)
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(cl=True)
