"""World-pose preservation, editable parent following, and transactional curves."""
import json,uuid
import maya.cmds as c
from maya_agent.rigs.integrated import builder,generic_objects,generic_animation


def run():
    prefix='_genericAnimation_'+uuid.uuid4().hex[:7]
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    real_ensure=generic_objects.ensure_controller;real_key=c.setKeyframe
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False);c.currentTime(0);c.namespace(add=prefix)
        wrist=c.createNode('joint',name=prefix+':wrist');finger=c.createNode('joint',name=prefix+':finger',parent=wrist);c.setAttr(finger+'.tx',2)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=prefix+'Rig')
        parent=c.createNode('transform',name=prefix+':parent')
        for t,v in ((0,0),(4,15),(8,-10)):
            c.setKeyframe(parent,at='tx',t=t,v=v);c.setKeyframe(parent,at='ry',t=t,v=v*3)
        def prop(name):
            p=c.createNode('joint',name=prefix+':'+name)
            c.setAttr(p+'.jointOrient',-123,18,-15);c.setAttr(p+'.scale',4.5,2.4,2.4)
            c.setAttr(p+'.segmentScaleCompensate',False)
            for f,v in ((0,8),(4,10),(8,4)):
                c.setKeyframe(p,at='tx',t=f,v=v);c.setKeyframe(p,at='rz',t=f,v=v*10)
            return p
        p=prop('prop');baseline={}
        for f in range(9):c.currentTime(f);baseline[f]=world(p)
        c.currentTime(0)
        # Reproduce an existing old prop, then explicitly repair it.
        generic_objects.ensure_controller=lambda character,owner,**kwargs:real_ensure(character,owner)
        data=generic_objects.add(p,parent,rig['root']);generic_objects.ensure_controller=real_ensure
        c.currentTime(4);old=world(p);assert error(old,baseline[4])>1
        report=generic_animation.repair(rig['root'],data['owner'])
        assert report['changed']
        assert error(world(p),baseline[4])<1e-5
        c.undo();assert error(world(p),old)<1e-5
        c.redo();assert error(world(p),baseline[4])<1e-5
        worst=0.
        for f in range(9):c.currentTime(f);worst=max(worst,error(world(p),baseline[f]))
        assert worst<1e-5,worst
        c.currentTime(4);position=world(p)[12:15]
        c.setKeyframe(parent,at='tx',t=4,v=17);c.dgdirty(parent)
        moved=world(p)[12:15];assert abs(moved[0]-position[0]-2)<1e-5
        generic_objects.switch(data['owner'],1,key=False)
        assert error(moved,world(p)[12:15])<1e-5
        # Fail partway through curve creation and verify original curves survive.
        c.currentTime(0);p2=prop('failProp');c.currentTime(0)
        edges={a:c.connectionInfo(p2+'.'+a,sfd=True) for a in generic_animation.TR}
        original_pose=world(p2);metadata=c.getAttr(rig['root']+'.integratedRigData');fixture=set(c.ls(long=True))
        def failing_key(*args,**kwargs):
            if args and '_baked_rotateY' in args[0]:raise RuntimeError('injected bake failure')
            return real_key(*args,**kwargs)
        c.setKeyframe=failing_key
        try:
            try:generic_objects.add(p2,parent,rig['root'])
            except RuntimeError as exc:assert 'injected bake failure' in str(exc)
            else:raise AssertionError('Expected bake failure')
        finally:c.setKeyframe=real_key
        assert set(c.ls(long=True))==fixture,(set(c.ls(long=True))-fixture)
        assert all(c.connectionInfo(p2+'.'+a,sfd=True)==e for a,e in edges.items())
        assert error(world(p2),original_pose)<1e-5
        assert c.getAttr(rig['root']+'.integratedRigData')==metadata
        return dict(passed=True,max_pose_error=worst,undo_redo=True,parent_edits_follow=True,mode_switch=True,partial_bake_rollback=True)
    finally:
        c.setKeyframe=real_key;generic_objects.ensure_controller=real_ensure
        added=set(c.ls(long=True))-before
        for n in added:
            if c.objExists(n) and c.nodeType(n).endswith('Constraint'):c.delete(n)
        for n in sorted(added,key=lambda x:x.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        for ns in c.namespaceInfo(listOnlyNamespaces=True,recurse=True) or []:
            if ns.startswith(prefix):c.namespace(removeNamespace=ns)
        c.currentTime(time);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(long=True))==before
