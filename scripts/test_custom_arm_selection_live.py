"""Maya integration checks for the fitted arm; remove only disposable test nodes."""
import importlib
import math
import maya.cmds as c
import maya.mel as mel
import maya.api.OpenMaya as om
import maya_agent.rigs.soft_limb as arm
import maya_agent.rigs.soft_limb.selection as fitting


def verify():
    importlib.reload(arm)
    importlib.reload(fitting)
    before = set(c.ls(long=True))
    old_selection = c.ls(sl=True,long=True) or []
    old_auto = c.autoKeyframe(q=True,state=True)
    old_frame = c.currentTime(q=True)
    old_namespace = c.namespaceInfo(currentNamespace=True)
    existing_keys = {n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))
                     for n in c.ls(type='animCurve')}
    c.autoKeyframe(state=False)
    namespaces=[]
    reports=[]
    try:
        cases=[('objects', [(30,5,2),(36,8,-1),(41,6,0)], False, 1),
               ('joints', [(-20,12,5),(-25,8,2),(-29,7,6)], True, 1.7),
               ('straight', [(0,25,0),(0,30,0),(0,38,0)], True, 1),
               ('unequal', [(15,30,2),(15.1,30.2,2.3),(23,34,-2)], False, 1)]
        for label, points, chain, scale in cases:
            group=c.createNode('transform',name='_armSelectionTest_'+label)
            c.setAttr(group+'.rotate',21,32,-11)
            c.setAttr(group+'.scale',scale,scale,scale)
            targets=[]
            for i,point in enumerate(points):
                n=c.createNode('joint' if chain else 'transform',
                               name='_armSelectionTarget_'+label+str(i),parent=targets[-1] if chain and targets else group)
                if chain: c.setAttr(n+'.jointOrient',11+i*8,-7,13)
                c.xform(n,ws=True,t=point,rotation=(21+i*13,-19+i*7,33-i*11))
                targets.append(c.ls(n,long=True)[0])
            skin=None
            if label=='joints':
                mesh=c.polyCube(name='_armSelectionSkinMesh')[0]
                c.xform(mesh,ws=True,t=points[1])
                skin=c.skinCluster(targets,mesh,toSelectedBones=True)[0]
                skin_before=[c.skinPercent(skin,mesh+'.vtx['+str(i)+']',q=True,value=True) for i in range(8)]
                vertices_before=[c.pointPosition(mesh+'.vtx['+str(i)+']',world=True) for i in range(8)]
            parents=[c.listRelatives(n,p=True,fullPath=True) for n in targets]
            original=[c.xform(n,q=True,ws=True,m=True) for n in targets]
            rig=arm.build_from_selection(targets=targets,namespace='_armSelectionCheck')
            namespaces.append(rig['namespace'])
            ns=rig['namespace']+':'
            assert c.ls(ns+'*',type='animCurve')==[]
            assert parents==[c.listRelatives(n,p=True,fullPath=True) for n in targets]
            initial_error=max(abs(a-b) for n,m in zip(targets,original)
                              for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
            assert initial_error<1e-5,(label,initial_error)
            if skin:
                assert skin_before==[c.skinPercent(skin,mesh+'.vtx['+str(i)+']',q=True,value=True) for i in range(8)]
                assert max(math.dist(p,c.pointPosition(mesh+'.vtx['+str(i)+']',world=True))
                           for i,p in enumerate(vertices_before))<1e-5
            offsets=[om.MMatrix(m)*om.MMatrix(c.xform(j,q=True,ws=True,m=True)).inverse()
                     for m,j in zip(original,rig['joints'])]
            # FK shoulder translation must move the root as well as the solver inputs.
            shoulder=ns+'shldrFK_L1'
            c.setAttr(shoulder+'.translateX',c.getAttr(shoulder+'.translateX')+2)
            c.setAttr(ns+'armFK_L1.rotateZ',c.getAttr(ns+'armFK_L1.rotateZ')-17)
            for target,joint,offset in zip(targets,rig['joints'],offsets):
                expected=list(offset*om.MMatrix(c.xform(joint,q=True,ws=True,m=True)))
                actual=c.xform(target,q=True,ws=True,m=True)
                assert max(abs(a-b) for a,b in zip(expected,actual))<1e-4,(label,target,'FK follow')
            for i,length in enumerate(rig['lengths']):
                measured=math.dist(c.xform(rig['joints'][i],q=True,ws=True,t=True),
                                   c.xform(rig['joints'][i+1],q=True,ws=True,t=True))
                assert abs(measured-length)<1e-4,(label,'length',length,measured)
            # Move the IK endpoint, then run the user's real recalculation function.
            c.setAttr(ns+'hand_L1.translateY',-.1*min(rig['lengths']))
            pre=[c.xform(n,q=True,ws=True,m=True) for n in targets]
            c.select(ns+'armFK_L1',r=True)
            assert mel.eval('EasyGameRig4_0_e8f0c3b3e6300189aca31ae83320ec92("*recalculate_node*")')==ns+'recalculate_node'
            mel.eval('kurok_recalculate_system(0);')
            recalc_error=max(abs(a-b) for n,m in zip(targets,pre)
                             for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
            assert recalc_error<1e-4,(label,'recalculate',recalc_error)
            reports.append({'case':label,'initial_error':initial_error,'recalculate_error':recalc_error,
                            'straight_input':rig['straight_input'],'skin_preserved':bool(skin)})
        # Guards: no scene mutation on an invalid target count, driven or animated targets.
        guard_group=c.createNode('transform',name='_armGuardFixture')
        guards=[c.createNode('transform',name='_armGuard'+str(i),parent=guard_group) for i in range(3)]
        for i,n in enumerate(guards):c.setAttr(n+'.translateX',i*4)
        bad_sets=[guards[:2], [guards[0],guards[0],guards[2]], targets]
        c.setKeyframe(guards[1],at='translateY',t=old_frame,v=0)
        bad_sets.append(guards)
        rejected=0
        for bad in bad_sets:
            nodes=set(c.ls(long=True))
            try: arm.build_from_selection(targets=bad,namespace='_armShouldReject')
            except ValueError:rejected+=1
            else:raise AssertionError('Invalid input accepted')
            assert set(c.ls(long=True))==nodes
        # Inject a failure after external output constraints to verify transactional cleanup.
        c.delete(c.listConnections(guards[1]+'.translateY',s=True,d=False))
        saved_connect=fitting.connect
        def fail_after_connect(rig,samples):
            saved_connect(rig,samples)
            raise RuntimeError('injected failure')
        fitting.connect=fail_after_connect
        nodes=set(c.ls(long=True))
        matrices=[c.xform(n,q=True,ws=True,m=True) for n in guards]
        try:
            try: arm.build_from_selection(targets=guards,namespace='_armRollback')
            except RuntimeError as exc:assert 'injected failure' in str(exc)
            else:raise AssertionError('Expected failure')
        finally:fitting.connect=saved_connect
        assert set(c.ls(long=True))==nodes
        assert not c.namespace(exists='_armRollback')
        assert all(max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))<1e-5
                   for n,m in zip(guards,matrices))
        return {'passed':True,'cases':reports,'rejected_inputs':rejected,'failure_rollback':True}
    finally:
        c.namespace(setNamespace=':')
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        for ns in namespaces:
            if c.namespace(exists=ns):c.namespace(removeNamespace=ns)
        c.namespace(setNamespace=old_namespace)
        c.autoKeyframe(state=old_auto)
        if c.currentTime(q=True)!=old_frame:c.currentTime(old_frame)
        c.select(old_selection,r=True) if old_selection else c.select(clear=True)
        assert set(c.ls(long=True))==before,'Original node set changed'
        for n,data in existing_keys.items():
            assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==data,n
