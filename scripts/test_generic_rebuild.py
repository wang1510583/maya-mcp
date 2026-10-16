"""Deleted generic DAGs must not leave parent motion in a new prop's OPM."""
import json,traceback
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs.integrated import builder,generic_objects,generic_hierarchy
from maya_agent.rigs import arm_ik,switch_panel

def run(history=False):
    ns='genericRebuildTest';assert not c.namespace(exists=ns)
    selection=c.ls(sl=True,l=True);frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    before=set(c.ls(uuid=True));owned=[ns];report={}
    def world(n):return om.MMatrix(c.xform(n,q=True,ws=True,m=True))
    def err(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False);c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist');finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',3)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig');owned += [rig['namespace'],rig['parts']['hand_L']['namespace']]
        parent=c.createNode('transform',name=ns+':originalParent');c.setAttr(parent+'.translate',9,7,-4);c.setAttr(parent+'.ry',21)
        loaded=c.createNode('transform',name=ns+':loaded');c.setAttr(loaded+'.translate',-4,8,3)
        prop=c.createNode('transform',name=ns+':prop',parent=parent);c.setAttr(prop+'.translate',3,4,5)
        base=c.createNode('composeMatrix',name=ns+':animatedOpm')
        c.setKeyframe(base,at='inputTranslateX',t=0,v=1);c.setKeyframe(base,at='inputTranslateX',t=10,v=5)
        c.currentTime(3);source=base+'.outputMatrix'
        old=[]
        # Actual DAG deletion leaves the matrix nodes and original parent edge.
        for i in (1,2):
            prefix=ns+':generic%02d'%i
            mode=c.createNode('transform',name=prefix+'_mode')
            match=c.createNode('transform',name=prefix+'_match',parent=mode)
            hold=c.createNode('holdMatrix',name=prefix+'_originalParentOffset');c.connectAttr(source,hold+'.inMatrix')
            matrix=c.createNode('multMatrix',name=prefix+'_preserveParent');old.append(matrix)
            c.connectAttr(hold+'.outMatrix',matrix+'.matrixIn[0]');c.connectAttr(match+'.worldMatrix[0]',matrix+'.matrixIn[1]')
            c.connectAttr(parent+'.worldInverseMatrix[0]',matrix+'.matrixIn[2]');source=matrix+'.matrixSum'
            c.delete(mode)
        c.connectAttr(source,prop+'.offsetParentMatrix');pose=world(prop)
        row=generic_objects.add(prop,loaded,rig['root'])
        assert err(pose,world(prop))<1e-5
        assert row['hierarchy_driver']['removed_orphan_inputs']==list(reversed(old))
        held=world(prop);c.setAttr(parent+'.translate',-20,40,9);c.setAttr(parent+'.rotate',-31,42,17)
        assert err(held,world(prop))<1e-5
        start=world(loaded);c.setAttr(loaded+'.translate',12,-8,6);c.setAttr(loaded+'.rotate',11,32,-23)
        assert err(held*start.inverse()*world(loaded),world(prop))<1e-5
        generic_objects.switch(row['owner'],1,key=False);held=world(prop)
        c.setAttr(loaded+'.rotate',-37,10,54);c.setAttr(parent+'.rx',73)
        assert err(held,world(prop))<1e-5
        start=world(row['master']);c.setAttr(row['master']+'.translate',4,-3,2);c.setAttr(row['master']+'.rotate',15,-29,34)
        assert err(held*start.inverse()*world(row['master']),world(prop))<1e-5
        # Genuine upstream OPM animation remains connected and active.
        retained=row['hierarchy_driver']['nodes'][1]
        assert c.connectionInfo(retained+'.matrixIn[0]',sfd=True)==base+'.outputMatrix'
        c.currentTime(9);assert err(world(prop),world(row['control']))<1e-5
        # Also repair an already-built contaminated input, keeping its pose.
        input_plug=row['owner'].rsplit('_mode',1)[0]+'_originalParentOffset.inMatrix'
        c.connectAttr(source,input_plug,force=True);pose=world(prop)
        repaired=generic_hierarchy.repair_orphan_input(rig['root'],row['owner'])
        assert repaired['changed'] and err(pose,world(prop))<1e-5
        if history:
            c.undo();assert c.connectionInfo(input_plug,sfd=True)==source;assert err(pose,world(prop))<1e-5
            c.redo();assert c.connectionInfo(input_plug,sfd=True)!=source;assert err(pose,world(prop))<1e-5
        held=world(prop);c.setAttr(parent+'.ry',-89);assert err(held,world(prop))<1e-5
        report=dict(passed=True,two_deleted_generations=True,creation_pose_preserved=True,parent_follow=True,
                    master_follow=True,upstream_animation_retained=True,existing_repair=True,undo_redo=history)
    except Exception:report.update(passed=False,traceback=traceback.format_exc())
    finally:
        for name in owned:
            nodes=c.ls(name+':*',type='constraint') or []
            if nodes:c.delete(nodes)
        for name in reversed(owned):
            if c.namespace(exists=name):
                nodes=c.ls(name+':*') or []
                if nodes:c.delete(nodes)
                c.namespace(removeNamespace=name)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(cl=True)
        c.file(modified=modified);arm_ik.install();switch_panel.install()
        report['original_nodes_retained']=before.issubset(set(c.ls(uuid=True)))
    return report
