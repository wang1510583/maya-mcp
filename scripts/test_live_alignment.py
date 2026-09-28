"""Temporary full-character checks for channel-preserving live surfaces."""
import uuid
import json
import maya.cmds as c
import maya.api.OpenMaya as om
from scripts.test_integrated_rig_live import fixture,remove


def expected(node):
    pivot=om.MTransformationMatrix();pivot.setTranslation(om.MVector(c.getAttr(node+'.rotatePivot')[0]),om.MSpace.kTransform)
    return list(pivot.asMatrix()*om.MMatrix(c.xform(node,q=True,ws=True,m=True)))


def aligned(part,role):
    data=part['live_alignment'];matrix=expected(data['targets'][role])
    if role in data.get('toe_follow',{}):
        source=data['inputs'][role];ball=data['toe_follow'][role]
        frame=om.MMatrix(expected(source))
        moved=frame*om.MMatrix(c.getAttr(ball+'.parentInverseMatrix[0]'))*om.MMatrix(c.getAttr(ball+'.matrix'))*om.MMatrix(c.getAttr(ball+'.parentMatrix[0]'))
        matrix=list(frame);matrix[12:15]=list(moved)[12:15]
    if role in data.get('pivot_sources',{}):
        pivot=om.MTransformationMatrix();pivot.setTranslation(om.MVector(c.getAttr(data['pivot_sources'][role]+'.rotatePivot')[0]),om.MSpace.kTransform)
        matrix=list(pivot.asMatrix()*om.MMatrix(c.xform(data['targets'][role],q=True,ws=True,m=True)))
    if role in data.get('position_targets',{}):matrix[12:15]=c.xform(data['position_targets'][role],q=True,ws=True,t=True)
    return matrix


def verify(animated=False):
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import live_alignment as live
    prefix='_liveAlignTest_'+uuid.uuid4().hex[:6]
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    try:
        group,parts=fixture(prefix,animated,True)
        c.currentTime(1);rig=build(parts,namespace=prefix)
        sample_frames=(1,1.5,3,4.5,5)
        nodes=[n for p in rig['parts'].values() for n in p.get('joints',[])]
        baseline={}
        for f in sample_frames:
            c.currentTime(f);baseline[f]={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
        c.currentTime(1)
        keys={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        for k,p in rig['parts'].items():
            if k.startswith(('arm','leg')):live.enable(p,k.split('_')[0])
        error=0;alignment=0
        for f in sample_frames:
            c.currentTime(f)
            for n,m in baseline[f].items():error=max(error,max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)))
            for k,p in rig['parts'].items():
                if 'live_alignment' not in p:continue
                for role,ctrl in p['live_controls'].items():
                    alignment=max(alignment,max(abs(a-b) for a,b in zip(c.xform(ctrl,q=True,ws=True,m=True),aligned(p,role))))
        assert error<1e-5,error
        assert alignment<1e-5,alignment
        assert keys=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        c.currentTime(3)
        edits=[]
        if not animated:
            for k,p in rig['parts'].items():
                if 'live_alignment' not in p:continue
                for role,ctrl in p['live_controls'].items():
                    old=c.xform(ctrl,q=True,ws=True,m=True)
                    c.rotate(11,7,-9,ctrl,relative=True,objectSpace=True)
                    c.move(.3,-.2,.1,ctrl,relative=True,worldSpace=True)
                    actual=c.xform(ctrl,q=True,ws=True,m=True)
                    err=max(abs(a-b) for a,b in zip(actual,aligned(p,role)))
                    assert err<1e-5,(k,role,err)
                    assert max(abs(a-b) for a,b in zip(actual,old))>1e-4,(k,role,'no response')
                    edits.append((k,role))
                if k.startswith('leg'):
                    c.setAttr(p['live_controls']['heel']+'.rotateX',25)
                    ctrl=p['live_controls']['foot']
                    assert max(abs(a-b) for a,b in zip(c.xform(ctrl,q=True,ws=True,m=True),aligned(p,'foot')))<1e-5
        cycles=c.cycleCheck([p['root'] for p in rig['parts'].values()],list=True) or []
        assert not cycles,cycles
        for p in rig['parts'].values():
            if 'live_alignment' in p:
                c.setAttr(p['root']+'.liveAlignment',False)
                for role,ctrl in p['live_controls'].items():
                    assert max(abs(a-b) for a,b in zip(c.xform(ctrl,q=True,ws=True,m=True),expected(p['controls'][role])))<1e-5
                live.remove(p['root'])
        assert keys=={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        return dict(animated=animated,pose_error=error,alignment_error=alignment,edited_controls=edits,cycles=cycles,curves_preserved=True)
    finally:
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before


def verify_integrated():
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs.soft_leg import set_adjustment_mode
    prefix='_liveIntegrated_'+uuid.uuid4().hex[:6]
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    mode=c.evaluationManager(q=True,mode=True)[0]
    try:
        group,parts=fixture(prefix,True,True)
        for key,p in parts.items():
            if key.startswith('arm'):p.update(live_alignment=True,space_upper_arm=True,space_wrist=True)
            if key.startswith('leg'):p.update(live_alignment=True,space_foot=True,space_knee=True)
        c.currentTime(1);rig=build(parts,namespace=prefix,general_root=group)
        count=sum(len(p.get('live_controls',{})) for p in rig['parts'].values());assert count==16
        for key,p in rig['parts'].items():
            if 'live_controls' not in p:continue
            for role,ctrl in p['live_controls'].items():
                if c.objExists(ctrl+'.global'):
                    c.setAttr(ctrl+'.global',1);assert c.getAttr(p['controls'][role]+'.global')==1
                    c.setAttr(ctrl+'.global',0)
        maximum=0
        for evaluation in ('off','serial','parallel'):
            c.evaluationManager(mode=evaluation)
            for f in (1,2.3,5,3,1.5):
                c.currentTime(f)
                for p in rig['parts'].values():
                    for role,ctrl in p.get('live_controls',{}).items():
                        maximum=max(maximum,max(abs(a-b) for a,b in zip(c.xform(ctrl,q=True,ws=True,m=True),aligned(p,role))))
        assert maximum<1e-5,maximum
        c.evaluationManager(mode=mode);c.currentTime(3)
        # Nonzero animated roll exercises guide mapping out of hidden input
        # space and compensation through the live channel relays.
        for p in rig['parts'].values():
            if p.get('live_alignment',{}).get('kind')!='leg':continue
            for role,values in (('heel',(-12,8)),('toe_end',(7,-16)),('ball',(15,-9)),('toe',(-8,12))):
                for f,value in zip((1,5),values):c.setKeyframe(p['live_controls'][role],at='rotateX',time=f,value=value)
        output=[n for p in rig['parts'].values() for n in p.get('joints',[])]
        poses={}
        for f in (1,2.7,3,4.4,5):
            c.currentTime(f);poses[f]={n:c.xform(n,q=True,ws=True,m=True) for n in output}
        c.currentTime(3)
        for side in ('L','R'):
            p=rig['parts']['leg_'+side];guides=set_adjustment_mode(p,True)['guides']
            for role in ('heel','toe_end','toe'):
                assert max(abs(a-b) for a,b in zip(c.xform(guides[role],q=True,ws=True,t=True),c.xform(p['live_controls'][role],q=True,ws=True,t=True)))<1e-5
            for guide in guides.values():c.move(.2,.1,-.3,guide,relative=True,worldSpace=True)
            requested={role:c.xform(guides[role],q=True,ws=True,t=True) for role in ('heel','toe_end','toe')}
            set_adjustment_mode(p,False)
            for role,pos in requested.items():
                assert max(abs(a-b) for a,b in zip(pos,c.xform(p['live_controls'][role],q=True,ws=True,t=True)))<1e-5
        pivot_error=0
        for f in poses:
            c.currentTime(f)
            pivot_error=max(pivot_error,max(abs(a-b) for n,m in poses[f].items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)))
        assert pivot_error<1e-4,pivot_error
        from maya_agent.rigs import live_edit
        for side in ('L','R'):
            p=rig['parts']['leg_'+side]
            live_edit.prepare(p['root'])
            for role in ('heel','toe_end','toe'):
                error=max(abs(a-b) for a,b in zip(c.xform(p['controls'][role],q=True,ws=True,rp=True),c.xform(p['live_controls'][role],q=True,ws=True,t=True)))
                assert error<1e-5,(role,'edit pivot',error)
        return dict(controls=count,evaluation_modes=['DG','serial','parallel'],alignment_error=maximum,
                    pivot_error=pivot_error,global_proxy=True,general_root=True,copy_error=rig['max_world_error'])
    finally:
        c.evaluationManager(mode=mode)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before


def verify_upgrade():
    """Extend a v1.1 layer without losing animated or unkeyed roll values."""
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs import live_alignment as live
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);rig=None;add=live._add_roll_controls
    try:
        c.autoKeyframe(state=False)
        prefix='_liveUpgrade_'+uuid.uuid4().hex[:6]
        group,parts=fixture(prefix,True,True)
        c.currentTime(3);rig=build(parts,namespace=prefix)
        live._add_roll_controls=lambda rig,data:None
        for key,p in rig['parts'].items():
            if key.startswith(('leg','arm')):live.enable(p,key.split('_')[0])
        live._add_roll_controls=add
        c.setAttr(rig['root']+'.integratedRigData',lock=False)
        c.setAttr(rig['root']+'.integratedRigData',json.dumps(rig),type='string',lock=True)
        for key,p in rig['parts'].items():
            if not key.startswith('leg'):continue
            node=p['controls']['heel']
            for f,value in ((1,-15),(5,20)):c.setKeyframe(node,at='rotateX',time=f,value=value)
        c.currentTime(3)
        for key,p in rig['parts'].items():
            if key.startswith('leg'):c.setAttr(p['controls']['heel']+'.rotateX',-23)
        output=[n for p in rig['parts'].values() for n in p.get('joints',[])]
        poses={n:c.xform(n,q=True,ws=True,m=True) for n in output}
        report=live.enable_character(rig['root'])
        assert max(abs(a-b) for n,m in poses.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-5
        assert report['controls']==16
        return report
    finally:
        live._add_roll_controls=add
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
