"""Uniform scaling against independent world-matrix and skinned-vertex expectations."""
import json,runpy,uuid,importlib
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

def run(animated=False,general=False,upgrade=False,skin_method=0,legacy=False):
    from maya_agent.rigs.integrated import builder,master_control,master_scale
    from maya_agent.rigs import arm_ik,foot_space,live_edit
    importlib.reload(master_scale);importlib.reload(master_control)
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True);busy=arm_ik._busy
    before=set(c.ls(uuid=True));original={n:c.xform(n,q=True,ws=True,m=True) for n in c.ls(type='transform',long=True)+c.ls(type='joint',long=True)}
    curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
    rig=None;prefix='_scaleTest_'+uuid.uuid4().hex[:7];arm_ik._busy=True;c.autoKeyframe(state=False)
    def matrix(n):return om.MMatrix(c.xform(n,q=True,ws=True,m=True))
    def diff(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        fixture,parts=suite['fixture'](prefix,animated,shoulders=True);c.currentTime(1)
        leaf=c.createNode('joint',name=prefix+'_extraBone',parent=parts['head']['targets'][-1]);c.setAttr(leaf+'.tx',.6)
        influences=[parts['body']['targets'][0],parts['body']['targets'][-1],parts['arm_L']['targets'][-1],parts['leg_R']['targets'][2],leaf]
        mesh=c.polyCube(name=prefix+'_skin',w=8,h=10,d=3,ch=False)[0];c.setAttr(mesh+'.ty',17);c.parent(mesh,fixture)
        skin=c.skinCluster(influences,mesh,tsb=True)[0]
        c.setAttr(skin+'.skinningMethod',skin_method)
        if skin_method==2:
            for i in range(8):c.setAttr(skin+'.blendWeights[%d]'%i,.7)
        for i in range(8):c.skinPercent(skin,mesh+'.vtx[%d]'%i,transformValue=[(influences[i%len(influences)],.6),(influences[(i+1)%len(influences)],.4)],zeroRemainingInfluences=True)
        for key,item in parts.items():
            if key.startswith('arm'):item.update(space_wrist=True,space_upper_arm=True,live_alignment=True)
            if key.startswith('leg'):item.update(space_foot=True,space_knee=True,live_alignment=True)
        enable=master_scale.enable
        if upgrade:master_scale.enable=lambda rig:None
        try:rig=builder.build(parts,namespace=prefix,general_root=fixture if general else None,zero_controls=True)
        finally:master_scale.enable=enable
        if upgrade:
            old={n:matrix(n) for p in rig['parts'].values() for n in p['controls'].values()}
            master_control.upgrade(rig['root']);rig=json.loads(c.getAttr(rig['root']+'.integratedRigData'))
            assert max(diff(list(m),list(matrix(n))) for n,m in old.items())<1e-6,'upgrade moved controls'
        master=rig['master_control'];plug=rig['overall_scale'];assert c.getAttr(plug)==1
        if legacy:
            # Recreate the released v1 graph, then migrate at non-unit scale.
            marker=rig['root']+'.'+master_scale.ATTRIBUTE;data=json.loads(c.getAttr(marker));old_rows=[]
            for row in data['skin_inputs']:
                wrapper=c.createNode('multMatrix',name=rig['namespace']+':masterSkinFrame00')
                c.connectAttr(row['influence'],wrapper+'.matrixIn[0]')
                c.connectAttr(c.connectionInfo(row['matrix']+'.matrixIn[2]',sfd=True),wrapper+'.matrixIn[1]')
                c.disconnectAttr(row['matrix']+'.matrixSum',row['destination'])
                if row['source']:c.connectAttr(row['source'],row['destination'])
                else:c.setAttr(row['destination'],*row['value'],type='matrix')
                dst=row['destination'].replace('.bindPreMatrix[','.matrix[')
                old_rows.append(dict(destination=dst,source=row['influence'],value=c.getAttr(dst),matrix=wrapper))
                c.connectAttr(wrapper+'.matrixSum',dst,force=True);data['created'].append(wrapper)
            data['skin_inputs']=old_rows;data['version']='1.0.0'
            c.setAttr(marker,lock=False);c.setAttr(marker,json.dumps(data),type='string',lock=True)
            c.setAttr(plug,2);c.setAttr(master+'.translate',3,-2,4);c.setAttr(master+'.rotate',17,-31,12)
            old_vertices=[c.pointPosition(mesh+'.vtx[%d]'%i,w=True) for i in range(8)]
            assert not c.skinCluster(skin,q=True,influence=True)
            master_control.upgrade(rig['root'])
            assert max(diff(v,c.pointPosition(mesh+'.vtx[%d]'%i,w=True)) for i,v in enumerate(old_vertices))<1e-5
            c.setAttr(plug,1);c.setAttr(master+'.translate',0,0,0);c.setAttr(master+'.rotate',0,0,0)
        # Paint tools discover influences through direct skin.matrix connections.
        assert set(c.ls(c.skinCluster(skin,q=True,influence=True),long=True))==set(c.ls(influences,long=True))
        assert len(c.skinPercent(skin,mesh+'.vtx[0]',q=True,transform=None))==len(influences)
        for index in c.getAttr(skin+'.matrix',mi=True):
            assert c.nodeType(c.connectionInfo(skin+'.matrix[%d]'%index,sfd=True).split('.')[0])=='joint'
        nodes=[leaf]
        for part in rig['parts'].values():
            nodes+=part.get('joints',[])+[r['target'] for r in part.get('original_target_mapping',[])]+list(part.get('zero_controls',{}).values())
        nodes=list(dict.fromkeys(nodes));rows=[]
        count=len(c.ls());master_control.attach(rig);assert len(c.ls())==count,'duplicate scale setup'
        for mode,foot in ((0,0),(1,0),(1,1),(0,1)):
            for s in ('L','R'):arm_ik.switch(rig['parts']['arm_'+s]['root'],mode,key=False);foot_space.switch(rig['parts']['leg_'+s]['root'],foot,key=False)
            poses={n:matrix(n) for n in nodes};vertices=[om.MPoint(*c.pointPosition(mesh+'.vtx[%d]'%i,w=True)) for i in range(8)]
            peak=0;skin_error=0
            for scale in (.25,.5,2,5):
                c.setAttr(plug,scale);c.setAttr(master+'.translate',3,-2,4);c.setAttr(master+'.rotate',17,-31,12);delta=matrix(master)
                errors={n:diff(list(m*delta),list(matrix(n))) for n,m in poses.items()};bad={n:e for n,e in errors.items() if e>2e-4}
                assert not bad,dict(mode=mode,foot=foot,scale=scale,bad=bad)
                peak=max(peak,max(errors.values()))
                for i,v in enumerate(vertices):skin_error=max(skin_error,diff(list(v*delta)[:3],c.pointPosition(mesh+'.vtx[%d]'%i,w=True)))
                assert skin_error<2e-4,dict(scale=scale,skin_error=skin_error)
            c.setAttr(plug,1);c.setAttr(master+'.translate',0,0,0);c.setAttr(master+'.rotate',0,0,0)
            rows.append(dict(mode=mode,foot=foot,matrix_error=peak,skin_error=skin_error))
        # Switching and editing must remain usable at a non-unit character size.
        c.setAttr(plug,2);c.setAttr(master+'.translate',3,-2,4);c.setAttr(master+'.rotate',17,-31,12)
        for mode in (1,0,1):
            watched=[r['target'] for p in rig['parts'].values() for r in p.get('original_target_mapping',[])]
            old={n:matrix(n) for n in watched}
            for s in ('L','R'):arm_ik.switch(rig['parts']['arm_'+s]['root'],mode,key=False);foot_space.switch(rig['parts']['leg_'+s]['root'],mode,key=False)
            switch_error=max(diff(list(m),list(matrix(n))) for n,m in old.items())
            assert switch_error<2e-4,('scaled switch',mode,switch_error)
        for side in ('L','R'):
            part=rig['parts']['arm_'+side];data=arm_ik._data(part['root']);driver=data['controls']['wrist']
            goal=live_edit._frame(driver);goal[12]+=.2;goal[13]+=.15
            live_edit._world(driver,goal,{})
            assert diff(list(goal),list(live_edit._frame(driver)))<1e-5,'scaled wrist input'
        c.setAttr(plug,1);c.setAttr(master+'.translate',0,0,0);c.setAttr(master+'.rotate',0,0,0)
        # Key the scale after capturing the same original animation at subframes.
        base={};vbase={}
        for f in (1,1.5,2,2.75,3,4.5,5):
            c.currentTime(f);base[f]={n:matrix(n) for n in nodes};vbase[f]=[om.MPoint(*c.pointPosition(mesh+'.vtx[%d]'%i,w=True)) for i in range(8)]
        for f,v in ((1,.5),(3,2),(5,1)):c.setKeyframe(master,at='overallScale',t=f,v=v,itt='linear',ott='linear')
        playback=0;details=[]
        for f,poses in base.items():
            c.currentTime(f);delta=matrix(master)
            errors={n:diff(list(m*delta),list(matrix(n))) for n,m in poses.items()}
            vertices={str(i):diff(list(v*delta)[:3],c.pointPosition(mesh+'.vtx[%d]'%i,w=True)) for i,v in enumerate(vbase[f])}
            playback=max(playback,max(errors.values()),max(vertices.values()))
            if max(errors.values())>2e-4 or max(vertices.values())>2e-4:details.append(dict(frame=f,nodes={n:e for n,e in errors.items() if e>2e-4},vertices=vertices))
        assert playback<2e-4,('playback',playback,details)
        return dict(passed=True,animated=animated,general=general,upgrade=upgrade,skin_method=skin_method,legacy=legacy,rows=rows,playback_error=playback)
    finally:
        if rig:suite['remove'](rig)
        added=set(c.ls(uuid=True))-before
        for uid in added:
            found=c.ls(uid,long=True) or []
            if found and c.objectType(found[0],isAType='constraint'):c.delete(found)
        for uid in added:
            found=c.ls(uid,long=True) or []
            if found:c.delete(found)
        c.currentTime(frame);c.autoKeyframe(state=auto);arm_ik._busy=busy;c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(uuid=True))==before,'original node set changed'
        for n,keys in curves.items():assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==keys,'original curves changed'
        assert max([diff(m,c.xform(n,q=True,ws=True,m=True)) for n,m in original.items()] or [0])<1e-8,'original pose changed'
        c.file(modified=modified)

def failure():
    from maya_agent.rigs.integrated import builder,master_control,master_scale
    from maya_agent.rigs import arm_ik
    for module in (master_scale,master_control,builder):importlib.reload(module)
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    original=set(c.ls(uuid=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or [];modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    prefix='_scaleRollback_'+uuid.uuid4().hex[:7];arm_ik._busy=True;c.autoKeyframe(state=False);attach=master_control.attach
    try:
        fixture,parts=suite['fixture'](prefix,True,shoulders=True);c.currentTime(1)
        target=parts['body']['targets'][0]
        mesh=c.polyCube(name=prefix+'_skin',ch=False)[0];skin=c.skinCluster([target],mesh,tsb=True)[0]
        nodes=set(c.ls(uuid=True));plugs=[target+'.offsetParentMatrix',skin+'.matrix[0]',skin+'.bindPreMatrix[0]'];sources={p:c.connectionInfo(p,sfd=True) for p in plugs}
        poses={n:c.xform(n,q=True,ws=True,m=True) for p in parts.values() for n in p['targets']}
        def broken(rig):attach(rig);raise RuntimeError('injected after scale installation')
        master_control.attach=broken
        try:builder.build(parts,namespace=prefix,zero_controls=True)
        except RuntimeError as exc:assert 'injected after scale' in str(exc),str(exc)
        else:raise AssertionError('failure was not injected')
        assert set(c.ls(uuid=True))==nodes,'failed build leaked nodes'
        assert all(c.connectionInfo(p,sfd=True)==s for p,s in sources.items()),'original matrix connections lost'
        assert max(abs(a-b) for n,m in poses.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-5,'failed build changed pose'
        return dict(passed=True,late_failure_original_opm_and_skin_restored=True)
    finally:
        master_control.attach=attach
        for uid in set(c.ls(uuid=True))-original:
            nodes=c.ls(uid,long=True) or []
            if nodes:c.delete(nodes)
        c.currentTime(frame);c.select(sel,r=True) if sel else c.select(clear=True);c.autoKeyframe(state=auto);arm_ik._busy=busy;c.file(modified=modified)
        assert set(c.ls(uuid=True))==original
