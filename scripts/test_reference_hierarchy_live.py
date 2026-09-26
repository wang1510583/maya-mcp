"""Reference hierarchy/head regression; temporary fixtures, never replace scene."""
import runpy,uuid,math
from pathlib import Path
import maya.cmds as c


def verify(animated=False,general=False,spaces=False):
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    rig=None;prefix='_referenceHierarchy_'+uuid.uuid4().hex[:6]
    try:
        root,parts=suite['fixture'](prefix,animated,shoulders=True)
        if spaces:
            parts['head']['space_head']=True
            for side in ('L','R'):
                parts['arm_'+side].update(space_upper_arm=True,space_wrist=True)
                parts['leg_'+side]['space_foot']=True
        c.currentTime(1)
        rig=build(parts,namespace=prefix,general_root=root if general else None)
        assert rig['max_world_error']<1e-4
        body=rig['parts']['body'];head=rig['parts']['head']
        assert len(head['neck_blends'])==1
        assert c.orientConstraint(head['neck_blends'][0],q=True,targetList=True)==[head['chest_orientation'],head['controls']['head']]
        for k,p in rig['parts'].items():
            path=c.ls(p['root'],long=True)[0]
            assert body['controls']['hips']+'|' not in path and body['controls']['chest']+'|' not in path
        def pose(n):return c.xform(n,q=True,ws=True,m=True)
        def add(n,a,v):
            v+=c.getAttr(n+'.'+a)
            if c.listConnections(n+'.'+a,s=True,d=False):c.setKeyframe(n,at=a,t=c.currentTime(q=True),v=v)
            else:c.setAttr(n+'.'+a,v)
            c.dgdirty(n)
        def check_delta(n,old,dx):
            new=pose(n);assert abs(new[12]-old[12]-dx)<1e-4,(n,dx,old[12:15],new[12:15])
            assert max(abs(new[i]-old[i]) for i in (13,14))<1e-4
        c.currentTime(3 if animated else 1)
        feet=[rig['parts']['leg_'+s]['controls']['foot'] for s in ('L','R')]
        hips=[rig['parts']['leg_'+s]['controls']['hip'] for s in ('L','R')]
        old={n:pose(n) for n in feet+hips}
        add(body['controls']['hips'],'translateX',2)
        for n in feet:check_delta(n,old[n],0)
        for n in hips:check_delta(n,old[n],2)
        arms=[rig['parts']['arm_'+s]['controls']['shoulder_fk'] for s in ('L','R')]
        clavicles=[rig['parts']['shoulder_'+s]['controls']['clavicle'] for s in ('L','R')]
        neck=head['controls']['neck1'];head_ctrl=head['controls']['head']
        old={n:pose(n) for n in arms+clavicles+[neck,head_ctrl]}
        add(body['controls']['chest'],'translateX',1)
        for n in arms+clavicles+[neck,head_ctrl]:check_delta(n,old[n],1)
        old={n:pose(n) for n in arms};add(clavicles[0],'translateX',1)
        # Clavicle axes can differ from world; the matching arm must move.
        assert math.dist(old[arms[0]][12:15],pose(arms[0])[12:15])>.1
        assert max(abs(a-b) for a,b in zip(old[arms[1]],pose(arms[1])))<1e-4
        old_neck=pose(neck);old_head=pose(head_ctrl)
        add(head_ctrl,'rotateY',20)
        assert max(abs(a-b) for a,b in zip(old_neck[:12],pose(neck)[:12]))>.01
        if not animated:
            # With identity reference fixture frames: half of a head turn reaches neck.
            import maya.api.OpenMaya as om
            delta=om.MMatrix(pose(neck))*om.MMatrix(old_neck).inverse()
            angle=math.degrees(om.MTransformationMatrix(delta).rotation(asQuaternion=True).asAxisAngle()[1])
            assert abs(angle-10)<1e-3,angle
        if general:
            old={n:pose(n) for n in feet+hips+arms+[head_ctrl]}
            add(root,'translateZ',3)
            for n in old:
                new=pose(n)
                assert abs(new[14]-old[n][14]-3)<1e-4,(n,old[n][12:15],new[12:15])
        import maya.mel as mel
        snap_error=0.0
        if mel.eval('exists kurok_recalculate_system'):
            for side in ('L','R'):
                arm=rig['parts']['arm_'+side];fk=arm['controls']['middle_fk']
                add(fk,'rotateY',17);add(fk,'translateZ',.2)
                nodes=arm['joints']+parts['arm_'+side]['targets']
                before_snap={n:pose(n) for n in nodes};last=None
                for _ in range(5):
                    c.select(fk,r=True);mel.eval('kurok_recalculate_system(0);')
                    error=max(abs(a-b) for n,m in before_snap.items() for a,b in zip(m,pose(n)))
                    snap_error=max(snap_error,error)
                    current={n:pose(n) for n in arm['controls'].values() if isinstance(n,str) and c.objExists(n)}
                    if last:assert max(abs(a-b) for n,m in last.items() for a,b in zip(m,current[n]))<1e-4
                    last=current
                assert snap_error<1e-4,snap_error
        return dict(passed=True,animated=animated,general_root=general,spaces=spaces,
                    copied_world_error=rig['max_world_error'],parts=len(rig['parts']),head_half_blend=True,
                    feet_stay_world=True,hip_follows_pelvis=True,shoulder_point_link=True,snap_error=snap_error)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before


def verify_head_only(count=4):
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    prefix='_headOnly_'+uuid.uuid4().hex[:6]
    try:
        targets=[]
        for i in range(count):
            n=c.createNode('transform',name=prefix+'_target'+str(i));targets.append(n)
            for f in (1,2,3):
                values=[i*.4+f*.1,12+i*2,f*.2,i*13+f*3,40+i*9-f*2,i*4+f]
                for a,v in zip([p+x for p in ('translate','rotate') for x in 'XYZ'],values):c.setKeyframe(n,at=a,t=f,v=v)
        c.currentTime(1)
        rig=build({'head':dict(targets=targets,copy_animation=True,start_frame=1,end_frame=3,space_head=True)},namespace=prefix)
        assert rig['max_world_error']<1e-4
        assert len(rig['parts']['head']['neck_blends'])==count-1
        return dict(passed=True,targets=count,copy_error=rig['max_world_error'],without_body=True)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
