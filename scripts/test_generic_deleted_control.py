"""Deleted animator rebuild, original poses, mode-panel links and rollback."""
import json,uuid
import maya.cmds as c
from maya_agent.rigs.integrated import builder,generic_objects as go
from maya_agent.rigs import switch_panel


def run():
    ns='_deletedGeneric_'+uuid.uuid4().hex[:7]
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    real_ensure=go.ensure_controller
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False);c.currentTime(0);c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist')
        finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',2)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig')
        parent=c.createNode('transform',name=ns+':parent')
        p=c.createNode('joint',name=ns+':prop');child=c.createNode('joint',name=ns+':child',parent=p)
        c.setAttr(child+'.tx',2);c.setAttr(p+'.jointOrient',23,-17,10)
        for t,v in ((0,0),(4,15),(8,-10)):
            c.setKeyframe(parent,at='tx',t=t,v=v);c.setKeyframe(parent,at='ry',t=t,v=v*3)
            c.setKeyframe(p,at='tx',t=t,v=v*.2+5);c.setKeyframe(p,at='rz',t=t,v=v*2)
        baseline={}
        for f in range(9):c.currentTime(f);baseline[f]=world(p)
        c.currentTime(0);data=go.add(p,parent,rig['root'])
        panel=switch_panel.build(rig['root'])
        # A real registration must remain protected.
        try:go.add(p,parent,rig['root'])
        except ValueError:pass
        else:raise AssertionError('Duplicate accepted')
        worst=0.
        for cycle in range(2):
            c.delete(data['control']);old=data
            # Failed new construction leaves the deleted-control state intact.
            fixture=set(c.ls(long=True));meta=c.getAttr(rig['root']+'.integratedRigData');pose=world(p)
            def fail(*args,**kwargs):raise RuntimeError('injected rebuild failure')
            go.ensure_controller=fail
            try:
                try:go.add(p,parent,rig['root'])
                except RuntimeError as exc:assert 'injected rebuild failure' in str(exc)
                else:raise AssertionError('Expected failure')
            finally:go.ensure_controller=real_ensure
            assert set(c.ls(long=True))==fixture
            assert c.getAttr(rig['root']+'.integratedRigData')==meta
            assert error(world(p),pose)<1e-5
            data=go.add(p,parent,rig['root'])
            assert not c.objExists(old['owner'])
            assert data['number']==old['number']==1
            assert not c.listRelatives(p,parent=True)
            assert c.listRelatives(child,parent=True)==[p]
            for f in range(9):c.currentTime(f);worst=max(worst,error(world(p),baseline[f]))
            assert worst<1e-5,worst
            # Query-only time changes are undoable in Maya; return before undo.
            c.currentTime(0)
            switch_panel.build(rig['root'])
            handles=[n for n in c.ls(ns+'Rig:*.spaceSliderData',o=True) or [] if json.loads(c.getAttr(n+'.spaceSliderData')).get('role')=='generic_1']
            assert len(handles)==1
            assert c.listConnections(handles[0]+'.switchOwner',s=True,d=False)==[data['owner']]
            pose=world(p);go.switch(data['owner'],1,key=False);assert error(pose,world(p))<1e-5
            go.switch(data['owner'],0,key=False)
        # Static source is also recoverable without an animation receipt.
        static=c.createNode('transform',name=ns+':static');c.setAttr(static+'.tx',7)
        row=go.add(static,parent,rig['root']);c.delete(row['control'])
        replaced=go.add(static,parent,rig['root']);assert abs(c.getAttr(replaced['control']+'.tx')-7)<1e-5
        c.undo();assert not c.objExists(replaced['control']) and c.objExists(row['owner'])
        c.redo();assert c.objExists(replaced['control']) and not c.objExists(row['owner'])
        # Existing v1.26.10 records have only the animation-transfer backup.
        legacy=c.createNode('transform',name=ns+':legacy')
        c.setKeyframe(legacy,at='tx',t=0,v=5);c.setKeyframe(legacy,at='tx',t=8,v=9)
        legacy_poses={}
        for f in range(9):c.currentTime(f);legacy_poses[f]=world(legacy)
        c.currentTime(0);row=go.add(legacy,parent,rig['root'])
        assert row.get('animation_transfer')
        del row['source_backup']
        def metadata(node,attr,data):
            c.setAttr(node+'.'+attr,lock=False);c.setAttr(node+'.'+attr,json.dumps(data),type='string',lock=True)
        metadata(row['owner'],'genericSpaceData',row)
        r=json.loads(c.getAttr(rig['root']+'.integratedRigData'))
        r['generic_objects']=[row if x['owner']==row['owner'] else x for x in r['generic_objects']]
        metadata(rig['root'],'integratedRigData',r)
        c.delete(row['control'])
        new_parent=c.createNode('transform',name=ns+':newParent');c.setAttr(new_parent+'.ry',30)
        replaced=go.add(legacy,new_parent,rig['root'])
        assert replaced['parent_uuid']==c.ls(new_parent,uuid=True)[0]
        for f in range(9):c.currentTime(f);assert error(world(legacy),legacy_poses[f])<1e-5
        # New ordinary target keys take precedence over old creation backups.
        c.currentTime(0);c.delete(replaced['control'])
        legacy=c.parent(legacy,new_parent,relative=True)[0]
        for t,v in ((0,12),(3.5,-6),(8,25)):
            c.setKeyframe(legacy,at='tx',t=t,v=v);c.setKeyframe(legacy,at='rz',t=t,v=v*2)
        c.setAttr(legacy+'.ty',17)
        live_edges={a:c.connectionInfo(legacy+'.'+a,sfd=True) for a in ('tx','ty','tz','rx','ry','rz')}
        curves={edge.split('.')[0]:(c.keyframe(edge.split('.')[0],q=True,tc=True),c.keyframe(edge.split('.')[0],q=True,vc=True)) for edge in live_edges.values() if edge}
        live_poses={}
        for f in list(range(9))+[3.5]:c.currentTime(f);live_poses[f]=world(legacy)
        c.currentTime(0);fixture=set(c.ls(long=True));meta=c.getAttr(rig['root']+'.integratedRigData')
        go.ensure_controller=fail
        try:
            try:go.add(legacy,parent,rig['root'])
            except RuntimeError as exc:assert 'injected rebuild failure' in str(exc)
            else:raise AssertionError('Expected failure')
        finally:go.ensure_controller=real_ensure
        assert set(c.ls(long=True))==fixture
        assert c.getAttr(rig['root']+'.integratedRigData')==meta
        assert all(c.connectionInfo(legacy+'.'+a,sfd=True)==edge for a,edge in live_edges.items())
        for f,w in live_poses.items():c.currentTime(f);assert error(world(legacy),w)<1e-5
        c.currentTime(0);replaced=go.add(legacy,parent,rig['root'])
        assert c.listRelatives(legacy,parent=True)==[new_parent]
        current_error=0.
        for f,w in live_poses.items():c.currentTime(f);current_error=max(current_error,error(world(legacy),w))
        assert current_error<1e-5,current_error
        for curve,keys in curves.items():assert keys==(c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))
        return dict(passed=True,max_pose_error=worst,repeated_recreate=True,rollback=True,panel=True,static=True,undo_redo=True,legacy_backup=True,new_parent=True,current_animation_error=current_error,current_curves_retained=True,current_inputs_rollback=True)
    finally:
        go.ensure_controller=real_ensure
        added=set(c.ls(long=True))-before
        for n in added:
            if c.objExists(n) and c.nodeType(n).endswith('Constraint'):c.delete(n)
        for n in sorted(added,key=lambda x:x.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        for name in c.namespaceInfo(listOnlyNamespaces=True,recurse=True) or []:
            if name.startswith(ns):c.namespace(removeNamespace=name)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(long=True))==before
