"""Repeat snap regression with an off-plane roll reference; L/R and keyed inputs."""
import uuid
import maya.cmds as c
import maya.mel as mel


def verify(side='L',animated=False,old_reference=False):
    from maya_agent.rigs.soft_limb import build_from_selection
    from maya_agent.rigs.soft_limb.easy_rig import repair_recalculate_node
    from maya_agent.rigs.soft_leg import cleanup
    ns='_repeatAlign_'+uuid.uuid4().hex[:7]
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    old_keys={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
    try:
        targets=[]
        for i,p in enumerate([(-4.8,3.5,0),(-2.8,2.7,.3),(1.2,1.7,1.8)]):
            n=c.createNode('transform',name=ns+'_source'+str(i));c.xform(n,ws=True,t=p,ro=(i*17,12-i*15,7+i*23));targets.append(n)
        if animated:
            for i,n in enumerate(targets):
                for t,v in [(frame,0),(frame+1,.2),(frame+2,-.1)]:
                    c.setKeyframe(n,at='rotateX',t=t,v=17*i+v*20)
        rig=build_from_selection(targets,namespace=ns,side=side,copy_animation=animated,start_frame=frame,end_frame=frame+2)
        fk=rig['controls']['middle_fk'];pole=rig['controls']['pole_locator'];ref=ns+':recalculate_node.translate_orient_pivot3'
        assert c.connectionInfo(ref,sourceFromDestination=True)==pole+'.visibility'
        # A derived elbow-roll reference must never feed a changed bend plane into
        # a pose-preserving snap. This deterministic offset reproduces that defect.
        c.setAttr(ns+':locator3.translateX',c.getAttr(ns+':locator3.translateX')+2)
        if old_reference:c.connectAttr(ns+':locator3.visibility',ref,force=True)
        for a,d in [('translateY',.5),('translateZ',.4),('rotateX',-22),('rotateY',35),('rotateZ',-51)]:
            value=c.getAttr(fk+'.'+a)+d
            if animated:c.setKeyframe(fk,at=a,t=frame,v=value);c.dgdirty(fk)
            else:c.setAttr(fk+'.'+a,value)
        def pose(nodes):return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
        def error(expected):return max(abs(a-b) for n,m in expected.items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
        inputs=[rig['controls'][k] for k in ('shoulder_fk','middle_fk','end_fk','end_locator','pole_locator')]
        original=pose(rig['joints']+targets);initial_error=None
        if old_reference:
            c.select(fk,r=True);mel.eval('kurok_recalculate_system(0);')
            initial_error=error(original);assert initial_error>1e-3,initial_error
            repaired=repair_recalculate_node(ns);assert repaired['changed']
            assert not repair_recalculate_node(ns)['changed']
            original=pose(rig['joints']+targets)
        control_pose=None;max_output=0;max_repeat=0
        for i in range(10):
            c.select(fk,r=True);mel.eval('kurok_recalculate_system(0);')
            max_output=max(max_output,error(original))
            if control_pose:max_repeat=max(max_repeat,error(control_pose))
            else:control_pose=pose(inputs)
        assert max_output<1e-4,max_output
        assert max_repeat<1e-4,max_repeat
        return dict(passed=True,side=side,animated=animated,repeats=10,old_reference_error=initial_error,
                    output_error=max_output,repeat_error=max_repeat)
    finally:
        for n in c.ls(ns+':*',type='constraint') or []:
            if c.objExists(n):c.delete(n)
        if c.namespace(exists=ns):cleanup(ns)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
        for n,keys in old_keys.items():assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==keys
