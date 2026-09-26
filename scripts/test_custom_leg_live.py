"""Live isolated tests. No scene open/new/save; preserve the user's original nodes."""
import math
import maya.cmds as c


def matrices(nodes):return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}


def equal(before,tolerance=1e-5):
    error=max((abs(a-b) for n,m in before.items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m)),default=0)
    assert error<tolerance,error
    return error


def verify():
    from maya_agent.rigs.soft_leg import _build_template as build,build_from_selection,set_adjustment_mode,cleanup
    from maya_agent.rigs.soft_leg.adjustment import resolve
    import maya.mel as mel
    before=set(c.ls(long=True))
    original=matrices(c.ls(type='transform',long=True))
    selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True)
    frame=c.currentTime(q=True)
    namespaces=[]
    fixtures=[]
    report={}
    try:
        c.autoKeyframe(state=False)
        rig=build(namespace='_legCheck',offset=(30,0,0));namespaces.append(rig['namespace'])
        root,data=resolve(rig)
        ns=rig['namespace']+':'
        assert rig['baseline_max_error']<1e-6
        assert not c.ls(ns+'*',type='script')
        assert len(c.listConnections(ns+'recalculate_node',s=True,d=False,p=True))==13
        assert len(c.listConnections(ns+'straight_leg_tool',s=True,d=False,p=True))==3
        assert len(c.listConnections(ns+'barn_easy_IK_system',s=True,d=False,p=True))==4
        report['native_graph_and_metadata']=True
        initial=matrices(rig['joints'])
        heel=rig['controls']['heel']
        c.setAttr(heel+'.rotateX',20)
        old_roll=c.xform(rig['joints'][2],q=True,ws=True,t=True)
        c.setAttr(heel+'.rotateX',0)
        equal(initial)
        for i in range(2):
            set_adjustment_mode(root,True)
            for key,guide in data['guides'].items():
                assert not c.getAttr(guide+'.translateX',lock=True)
                c.move(.05,0,-.3 if key=='heel' else .25,guide,r=True,ws=True)
            equal(initial)
            desired={k:c.xform(g,q=True,ws=True,t=True) for k,g in data['guides'].items()}
            set_adjustment_mode(root,False)
            equal(initial)
            for key,node in data['controls'].items():
                assert math.dist(c.xform(node,q=True,ws=True,rp=True),desired[key])<1e-5
                assert c.getAttr(data['guides'][key]+'.translateX',lock=True)
                assert c.getAttr(node+'.rotatePivotX',lock=True)
                assert not c.getAttr(node+'.rotateX',lock=True)
            assert not c.getAttr(data['group']+'.visibility')
        pivot=c.xform(heel,q=True,ws=True,rp=True)
        c.setAttr(heel+'.rotateX',20)
        new_roll=c.xform(rig['joints'][2],q=True,ws=True,t=True)
        assert math.dist(pivot,c.xform(heel,q=True,ws=True,rp=True))<1e-5
        assert math.dist(old_roll,new_roll)>.01,(old_roll,new_roll)
        c.setAttr(heel+'.rotateX',0);equal(initial)
        # Commit must also preserve pose when the user has manually posed the controls.
        c.setAttr(heel+'.rotateX',12)
        posed=matrices(rig['joints'])
        set_adjustment_mode(root,True)
        c.move(0,0,.2,data['guides']['toe_end'],r=True,ws=True)
        set_adjustment_mode(root,False);equal(posed)
        c.setAttr(heel+'.rotateX',0)
        pivots={k:c.xform(n,q=True,ws=True,rp=True) for k,n in data['controls'].items()}
        set_adjustment_mode(root,True)
        c.move(2,3,4,data['guides']['toe'],r=True)
        set_adjustment_mode(root,False,cancel=True)
        for k,n in data['controls'].items():assert math.dist(pivots[k],c.xform(n,q=True,ws=True,rp=True))<1e-5
        report['adjust_commit_cancel_reenter_pose_preserved']=True
        report['adjusted_heel_roll_changes_solver']=True
        # Original MEL discovery and operation still work after pivot editing.
        assert mel.eval('exists kurok_recalculate_system')
        c.select(rig['controls']['foot'],r=True)
        assert mel.eval('EasyGameRig4_0_e8f0c3b3e6300189aca31ae83320ec92("*recalculate_node*")')==ns+'recalculate_node'
        before_recalc=matrices(rig['joints'])
        mel.eval('kurok_recalculate_system(0);')
        report['easy_rig_recalculate_pose_error']=equal(before_recalc,1e-4)
        c.setKeyframe(rig['controls']['foot'],attribute='translateX',time=frame)
        set_adjustment_mode(root,True)
        set_adjustment_mode(root,False,cancel=True)
        report['animated_mode_allowed']=True
        cases=[[(40,12,1),(40,7,2),(40,2,0),(40,.4,3)],
               [(-18,14,-2),(-20,8,0),(-19,1,-3),(-22,.2,-3)],
               [(50,12,0),(50,7,0),(50,2,0),(50,0,2)]]
        for index,points in enumerate(cases):
            group=c.createNode('transform',name='_legFixture'+str(index));fixtures.append(group)
            targets=[]
            for i,p in enumerate(points):
                n=c.createNode('joint',name='_legTarget{}_{}'.format(index,i),parent=targets[-1] if targets else group)
                c.setAttr(n+'.jointOrient',10*i,5*i,-3*i)
                c.xform(n,ws=True,t=p)
                targets.append(n)
            pose=matrices(targets)
            fitted=build_from_selection(targets,namespace='_legFit'+str(index));namespaces.append(fitted['namespace'])
            equal(pose)
            set_adjustment_mode(fitted,True)
            _,setup=resolve(fitted)
            c.move(0,0,-.5,setup['guides']['heel'],r=True,ws=True)
            set_adjustment_mode(fitted,False)
            equal(pose)
            end_before=c.xform(targets[2],q=True,ws=True,t=True)
            foot=fitted['controls']['foot']
            c.setAttr(foot+'.translateZ',c.getAttr(foot+'.translateZ')+.2)
            assert math.dist(end_before,c.xform(targets[2],q=True,ws=True,t=True))>.05
            cleanup(fitted['namespace']);namespaces.remove(fitted['namespace'])
            assert all(c.objExists(n) for n in targets)
        report['four_target_fitting_joint_orient_straight_and_driving']=True
        # Shared native loader remains backward compatible with the arm.
        from maya_agent.rigs.soft_limb import build as arm_build
        arm=arm_build(namespace='_armLegRegression',offset=(65,0,0));namespaces.append(arm['namespace'])
        assert arm['baseline_max_error']<1e-5
        report['arm_loader_regression']=True
    finally:
        for ns in reversed(namespaces):cleanup(ns)
        for n in fixtures:
            if c.objExists(n):c.delete(n)
        c.currentTime(frame)
        c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
    assert set(c.ls(long=True))==before,sorted(set(c.ls(long=True))-before)
    report['original_scene_max_error']=equal(original)
    report['original_node_set_preserved']=True
    return report
