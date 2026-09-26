"""Create a limb below an already rigged parent without replacing that parent."""
import runpy,uuid
import maya.cmds as c


def verify():
    from maya_agent.rigs.integrated import build,builder
    suite=runpy.run_path('D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/test_integrated_rig_live.py')
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rigs=[]
    prefix='_parentDriver_'+uuid.uuid4().hex[:7]
    try:
        _,parts=suite['fixture'](prefix,True);c.currentTime(1)
        body=build({'body':parts['body']},namespace=prefix+'_body');rigs.append(body)
        parent=parts['body']['targets'][0]
        channels=[p+a for p in ('translate','rotate') for a in 'XYZ']
        inputs={a:c.connectionInfo(parent+'.'+a,sourceFromDestination=True) for a in channels}
        curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(body['parts']['body']['namespace']+':*',type='animCurve')}
        nodes=set(c.ls(long=True))
        for config in ({'body':parts['body']},{'leg_R':dict(parts['leg_R'],copy_animation=False)}):
            try:builder.preflight(config)
            except ValueError:pass
            else:raise AssertionError('Direct output overwrite / disabled-copy guard was bypassed')
            assert set(c.ls(long=True))==nodes
        leg=build({'leg_R':parts['leg_R']},namespace=prefix+'_leg',general_root=body['parts']['body']['controls']['hips']);rigs.append(leg)
        assert all(c.connectionInfo(parent+'.'+a,sourceFromDestination=True)==src for a,src in inputs.items())
        for n,keys in curves.items():assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==keys
        c.currentTime(3);target=parts['leg_R']['targets'][0];pose=c.xform(target,q=True,ws=True,t=True)
        hips=body['parts']['body']['controls']['hips']
        c.setKeyframe(hips,at='translateX',t=3,v=c.getAttr(hips+'.translateX')+1);c.dgdirty(hips)
        after=c.xform(target,q=True,ws=True,t=True)
        assert abs(after[0]-pose[0]-1)<1e-4,(pose,after)
        return dict(passed=True,parent_constraint_preserved=True,parent_animation_preserved=True,
                    world_animation_error=leg['max_world_error'],follow_once=True,direct_target_guard=True)
    finally:
        for rig in reversed(rigs):suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
