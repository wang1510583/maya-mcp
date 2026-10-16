"""Invoke run() deferred, outside an MCP undo chunk, to test native history."""
import json,traceback
import maya.cmds as c
from maya_agent.rigs.integrated import builder,generic_objects
from maya_agent.rigs import arm_ik,switch_panel

def run():
    ns='genericHistoryTest';assert not c.namespace(exists=ns)
    selection=c.ls(sl=True,l=True);frame=c.currentTime(q=True);modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True)
    namespaces=[ns];result={}
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def err(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False)
        c.namespace(add=ns);wrist=c.createNode('joint',name=ns+':wrist')
        finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',3)
        rig=builder.build({'hand_R':dict(targets=[finger])},namespace=ns+'Rig')
        namespaces += [rig['namespace'],rig['parts']['hand_R']['namespace']]
        parent=c.createNode('transform',name=ns+':parent');prop=c.createNode('transform',name=ns+':prop');c.setAttr(prop+'.tx',5)
        original=world(prop);meta=c.getAttr(rig['root']+'.integratedRigData')
        row=generic_objects.add(prop,parent,rig['root'])
        c.undo();assert c.getAttr(rig['root']+'.integratedRigData')==meta;assert not c.listRelatives(prop,p=True)
        assert err(world(prop),original)<1e-5
        c.redo();assert c.objExists(row['owner']);assert err(world(prop),original)<1e-5
        c.setAttr(parent+'.tx',7);before=world(prop)
        generic_objects.switch(row['owner'],1,key=False);assert err(world(prop),before)<1e-5
        c.undo();assert c.getAttr(row['global_plug'])==0;assert err(world(prop),before)<1e-5
        c.redo();assert c.getAttr(row['global_plug'])==1;assert err(world(prop),before)<1e-5
        panel=switch_panel.build(rig['root']);count=len(c.ls(rig['namespace']+':*'))
        prop2=c.createNode('transform',name=ns+':prop2');generic_objects.add(prop2,parent,rig['root'])
        switch_panel.build(rig['root']);assert c.objExists(rig['namespace']+':switch_generic_2')
        c.undo();assert not c.objExists(rig['namespace']+':switch_generic_2')
        c.redo();assert c.objExists(rig['namespace']+':switch_generic_2')
        c.currentTime(0);generic_objects.switch(row['owner'],0,key=True)
        hidden=row['offsets'][1]+'.tx';c.setKeyframe(hidden,t=3,v=50,ott='step')
        c.currentTime(2);pose=world(prop)
        old_keys=(c.keyframe(hidden,q=True,tc=True),c.keyframe(hidden,q=True,vc=True))
        generic_objects.switch(row['owner'],1,key=True)
        new_keys=(c.keyframe(hidden,q=True,tc=True),c.keyframe(hidden,q=True,vc=True))
        c.undo();assert c.getAttr(row['global_plug'])==0
        assert old_keys==(c.keyframe(hidden,q=True,tc=True),c.keyframe(hidden,q=True,vc=True))
        c.redo();assert c.getAttr(row['global_plug'])==1
        assert new_keys==(c.keyframe(hidden,q=True,tc=True),c.keyframe(hidden,q=True,vc=True))
        c.currentTime(4);assert err(pose,world(prop))<1e-5
        from maya_agent.rigs.integrated import generic_hierarchy
        row=generic_objects._data(row['owner'])
        generic_hierarchy.remove_driver(row['hierarchy_driver'],prop,row['control'])
        c.parent(prop,row['compensation'],relative=True,noInvScale=True)
        row.pop('hierarchy_driver');row.pop('preserve_hierarchy')
        c.setAttr(row['owner']+'.genericSpaceData',lock=False);c.setAttr(row['owner']+'.genericSpaceData',json.dumps(row),type='string',lock=True)
        original=world(prop);old_parent=c.listRelatives(prop,p=True,f=True)
        generic_hierarchy.restore_original_parent(rig['root'],row['owner'])
        assert not c.listRelatives(prop,p=True);assert err(original,world(prop))<1e-5
        c.undo();assert c.listRelatives(prop,p=True,f=True)==old_parent;assert err(original,world(prop))<1e-5
        c.redo();assert not c.listRelatives(prop,p=True);assert err(original,world(prop))<1e-5
        result=dict(passed=True,create_undo_redo=True,switch_undo_redo=True,panel_refresh_undo_redo=True,keyed_hold_undo_redo=True,hierarchy_migration_undo_redo=True)
    except Exception:result=dict(passed=False,traceback=traceback.format_exc())
    finally:
        for name in namespaces:
            nodes=c.ls(name+':*',type='constraint') or []
            if nodes:c.delete(nodes)
        for name in reversed(namespaces):
            if c.namespace(exists=name):
                nodes=c.ls(name+':*') or []
                if nodes:c.delete(nodes)
                c.namespace(removeNamespace=name)
        c.currentTime(frame);c.select(selection,r=True) if selection else c.select(cl=True)
        c.autoKeyframe(state=auto);c.file(modified=modified);arm_ik.install();switch_panel.install()
    return result
