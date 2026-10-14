"""Disposable character tests; never open, replace or save the user's scene."""
import json, runpy, uuid, math
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om


def verify(animated=False, general=False, live=True, zero=True):
    from maya_agent.rigs.integrated import build
    from maya_agent.rigs.integrated.master_control import attach
    from maya_agent.rigs import arm_ik, live_edit, foot_space
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    frame=c.currentTime(q=True);selected=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    before=set(c.ls(uuid=True));rig=None;c.autoKeyframe(state=False)
    prefix='_masterTest_'+uuid.uuid4().hex[:7]
    try:
        fixture,parts=suite['fixture'](prefix,animated,shoulders=True)
        parts['body']['space_chest']=True;parts['head']['space_head']=True
        for side in ('L','R'):
            parts['arm_'+side].update(space_wrist=True,space_upper_arm=True,live_alignment=live)
            parts['leg_'+side].update(space_foot=True,space_knee=True,live_alignment=live)
        c.currentTime(1)
        rig=build(parts,namespace=prefix,general_root=fixture if general else None,zero_controls=zero)
        master=rig['master_control']
        assert list(c.getAttr(master+'.translate')[0])==[0,0,0]
        assert list(c.getAttr(master+'.rotate')[0])==[0,0,0]
        assert c.xform(master,q=True,ws=True,rp=True)==[0,0,0]
        registries={}
        for side in ('L','R'):
            for kind,count in (('arm',14),('leg',13)):
                registry=rig['parts'][kind+'_'+side]['namespace']+':recalculate_node'
                edges=c.listConnections(registry,s=True,d=False,p=True,c=True) or []
                registered=[src for src in edges[1::2] if src.endswith('.visibility')]
                assert len(registered)==count,(registry,registered)
                registries[registry]=edges
        count=len(c.ls());assert attach(rig)['control']==master and len(c.ls())==count
        rows=[]
        for mode,foot_mode in ((0,0),(1,0),(1,1),(0,1)):
            for part in [rig['parts']['arm_'+s] for s in ('L','R')]:
                arm_ik.switch(part['root'],mode,key=False)
            for side in ('L','R'):
                foot_space.switch(rig['parts']['leg_'+side]['root'],foot_mode,key=False)
            nodes=[]
            for part in rig['parts'].values():
                nodes+=part.get('joints',[])
                nodes += [r['target'] for r in part.get('original_target_mapping',[])]
            poses={n:om.MMatrix(c.xform(n,q=True,ws=True,m=True)) for n in nodes}
            worst=0
            for translation,rotation in [((3,-2,4),(0,0,0)),((0,0,0),(23,0,0)),((0,0,0),(0,-37,0)),((0,0,0),(0,0,19)),((4,2,-3),(17,-31,12))]:
                c.setAttr(master+'.translate',*translation);c.setAttr(master+'.rotate',*rotation)
                delta=om.MMatrix(c.xform(master,q=True,ws=True,m=True))
                errors={n:max(abs(a-b) for a,b in zip(list(m*delta),c.xform(n,q=True,ws=True,m=True))) for n,m in poses.items()}
                worst=max(worst,max(errors.values()))
                bad={n:e for n,e in errors.items() if e>1e-4}
                assert not bad,dict(mode=mode,translation=translation,rotation=rotation,errors=bad)
            if mode:
                # Native world-frame writes after moving the master must still
                # solve the visible wrist's requested position and orientation.
                for side in ('L','R'):
                    part=rig['parts']['arm_'+side];d=arm_ik._data(part['root']);driver=d['controls']['wrist']
                    goal=live_edit._frame(driver);goal[12]+=0.15;goal[13]+=0.2
                    live_edit._world(driver,goal,{})
                    assert max(abs(a-b) for a,b in zip(list(goal),list(live_edit._frame(driver))))<1e-5
                if zero:
                    from maya_agent.rigs import arm_ik_shared,live_arm_manual
                    for side in ('L','R'):
                        entry=arm_ik_shared.begin(rig['parts']['arm_'+side]['root'])
                        try:
                            proxy=entry['proxy'];c.setAttr(proxy+'.translateX',c.getAttr(proxy+'.translateX')+.12)
                            local=om.MTransformationMatrix(entry['local'])
                            local.setTranslation(om.MVector(*c.getAttr(proxy+'.translate')[0]),om.MSpace.kTransform)
                            goal=entry['input_basis']*local.asMatrix()*entry['parent']
                            live_arm_manual.update(entry)
                            error=max(abs(a-b) for a,b in zip(list(goal),list(live_edit._frame(entry['source']))))
                            assert error<1e-5,('shared wrist gesture',error)
                        finally:live_arm_manual.finish(entry,cancel=True)
            c.setAttr(master+'.translate',0,0,0);c.setAttr(master+'.rotate',0,0,0)
            rows.append(dict(mode=mode,foot_mode=foot_mode,max_matrix_error=worst))
        import maya.mel as mel
        alignment=None
        if not animated and mel.eval('exists kurok_recalculate_system'):
            alignment=0.0
            c.setAttr(master+'.translate',3,-2,4);c.setAttr(master+'.rotate',17,-31,12)
            for side in ('L','R'):
                for kind,key in (('arm','middle_fk'),('leg','foot')):
                    part=rig['parts'][kind+'_'+side]
                    watched=part['joints']+[r['target'] for r in part['original_target_mapping']]
                    poses={n:c.xform(n,q=True,ws=True,m=True) for n in watched}
                    for _ in range(3):
                        c.select(part['controls'][key],r=True)
                        assert mel.eval('EasyGameRig4_0_e8f0c3b3e6300189aca31ae83320ec92("*recalculate_node*")')==part['namespace']+':recalculate_node'
                        mel.eval('kurok_recalculate_system(0);')
                        alignment=max(alignment,max(abs(a-b) for n,m in poses.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
                        assert alignment<1e-4,('easy rig',side,kind,alignment)
            c.setAttr(master+'.translate',0,0,0);c.setAttr(master+'.rotate',0,0,0)
        # The offset is evaluated by DG during fractional-frame playback.
        base={}
        watched=[n for p in rig['parts'].values() for n in p.get('joints',[])]
        for f in (1,1.5,2,2.75,3,4.5,5):
            c.currentTime(f);base[f]={n:om.MMatrix(c.xform(n,q=True,ws=True,m=True)) for n in watched}
        for f,tx,ry in ((1,0,0),(3,5,25),(5,-2,-18)):
            c.setKeyframe(master,at='translateX',t=f,v=tx);c.setKeyframe(master,at='rotateY',t=f,v=ry)
        playback=0
        for f,poses in base.items():
            c.currentTime(f);delta=om.MMatrix(c.xform(master,q=True,ws=True,m=True))
            playback=max(playback,max(abs(a-b) for n,m in poses.items() for a,b in zip(list(m*delta),c.xform(n,q=True,ws=True,m=True))))
        assert playback<1e-4,('playback',playback)
        assert all(c.listConnections(n,s=True,d=False,p=True,c=True)==edges for n,edges in registries.items())
        return dict(passed=True,animated=animated,general=general,live=live,zero=zero,rows=rows,playback_error=playback,easy_rig_error=alignment)
    finally:
        c.autoKeyframe(state=False)
        if rig:suite['remove'](rig)
        for n in c.ls(prefix+'*',long=True) or []:
            if c.objExists(n):c.delete(n)
        # Transfer backups can retain unnamespaced proxy animation curves.
        # Their UUIDs were created by this fixture; original curves are excluded.
        for uid in set(c.ls(uuid=True))-before:
            found=c.ls(uid,long=True) or []
            if found and c.nodeType(found[0]).startswith('animCurve') and not c.listConnections(found[0]+'.output',s=False,d=True):
                c.delete(found[0])
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selected,r=True) if selected else c.select(clear=True)
        c.file(modified=modified)
        after=set(c.ls(uuid=True))
        assert after==before, dict(added=[c.ls(uid,long=True) for uid in after-before],missing=list(before-after))
