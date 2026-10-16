"""Native matrix driving, retained DAG, legacy migration and timeline parity."""
import json,traceback
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs.integrated import builder,generic_objects,generic_hierarchy
from maya_agent.rigs import arm_ik,switch_panel

def run():
    ns='genericHierarchyTest';assert not c.namespace(exists=ns)
    selection=c.ls(sl=True,l=True);frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    before=set(c.ls(uuid=True));owned=[ns];report={};warnings=[]
    cb=om.MCommandMessage.addCommandOutputCallback(lambda message,kind,*args:warnings.append(message) if kind==om.MCommandMessage.kWarning else None)
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def err(a,b):return max(abs(x-y) for x,y in zip(a,b))
    def save(row):
        c.setAttr(row['owner']+'.genericSpaceData',lock=False);c.setAttr(row['owner']+'.genericSpaceData',json.dumps(row),type='string',lock=True)
        rig_data=json.loads(c.getAttr(rig['root']+'.integratedRigData'));rig_data['generic_objects']=[row]
        c.setAttr(rig['root']+'.integratedRigData',lock=False);c.setAttr(rig['root']+'.integratedRigData',json.dumps(rig_data),type='string',lock=True)
    try:
        c.autoKeyframe(state=False);c.currentTime(0);c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist');finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',3)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig');owned += [rig['namespace'],rig['parts']['hand_L']['namespace']]
        original=c.createNode('transform',name=ns+':original');loaded=c.createNode('transform',name=ns+':loaded')
        prop=c.createNode('joint',name=ns+':prop',parent=original);child=c.createNode('joint',name=ns+':child',parent=prop)
        c.setAttr(prop+'.translate',3,5,2);c.setAttr(prop+'.jointOrient',13,-27,19);c.setAttr(child+'.tx',3)
        for n,a,v0,v1 in ((original,'ry',17,65),(original,'tx',4,20),(loaded,'rz',-12,23),(prop,'rx',8,32)):
            c.setKeyframe(n,at=a,t=0,v=v0);c.setKeyframe(n,at=a,t=10,v=v1)
        c.currentTime(0);path=c.ls(prop,l=True)[0];child_path=c.ls(child,l=True)[0];pose=world(prop)
        row=generic_objects.add(prop,loaded,rig['root']);control=row['control']
        assert path==c.ls(prop,l=True)[0] and child_path==c.ls(child,l=True)[0]
        assert err(pose,world(prop))<1e-5
        for t in (0,2.5,7,10):
            c.currentTime(t);assert err(world(control),world(prop))<1e-5
        c.currentTime(3);pose=world(prop);generic_objects.switch(row['owner'],1,key=True);assert err(pose,world(prop))<1e-5
        assert not any('tangent' in w.lower() or '切线' in w for w in warnings),warnings
        # Reconstitute the old sibling-controller layout, then migrate it.
        generic_hierarchy.remove_driver(row['hierarchy_driver'],prop,control)
        c.parent(prop,row['compensation'],relative=True,noInvScale=True)
        row.pop('hierarchy_driver');row.pop('preserve_hierarchy');save(row)
        expected={}
        for t in (0,1,2.5,3,4,7.5,10):
            c.currentTime(t);expected[t]=(world(prop),world(child))
        curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
        c.currentTime(3);generic_hierarchy.restore_original_parent(rig['root'],row['owner'])
        assert path==c.ls(prop,l=True)[0] and child_path==c.ls(child,l=True)[0]
        worst=0
        for t,(a,b) in expected.items():
            c.currentTime(t);worst=max(worst,err(a,world(prop)),err(b,world(child)),err(world(control),world(prop)))
        assert worst<1e-5,worst
        assert all(keys==(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n,keys in curves.items())
        report.update(passed=True,original_dag_preserved=True,migration_error=worst,animation_preserved=True,tangent_warning_absent=True)
    except Exception:report.update(passed=False,traceback=traceback.format_exc())
    finally:
        om.MMessage.removeCallback(cb)
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
