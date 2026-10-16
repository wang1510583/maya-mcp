"""Rebuild a prop with a disconnected marker without weakening duplicate checks."""
import traceback
import maya.cmds as c
from maya_agent.rigs.integrated import builder,generic_objects
from maya_agent.rigs import arm_ik,switch_panel

def run():
    ns='genericRegistrationTest';assert not c.namespace(exists=ns)
    selection=c.ls(sl=True,l=True);frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    owned=[ns];report={};real_ensure=generic_objects.ensure_controller
    before=set(c.ls(uuid=True))
    try:
        c.autoKeyframe(state=False);c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist')
        finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',3)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig')
        owned += [rig['namespace'],rig['parts']['hand_L']['namespace']]
        parent=c.createNode('transform',name=ns+':parent')
        prop=c.createNode('transform',name=ns+':prop');c.setAttr(prop+'.translate',4,5,6)
        c.setKeyframe(prop,at='tx',t=0,v=4);c.setKeyframe(prop,at='tx',t=10,v=12)
        curve=c.listConnections(prop+'.tx',s=True,d=False,type='animCurve')[0]
        keys=(c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))
        owner=c.createNode('transform',name=ns+':deletedOwner')
        c.addAttr(prop,ln='genericSpaceOwner',at='message');c.connectAttr(owner+'.message',prop+'.genericSpaceOwner');c.delete(owner)
        pose=c.xform(prop,q=True,ws=True,m=True)
        def fail(*args,**kwargs):raise RuntimeError('Intentional construction failure')
        generic_objects.ensure_controller=fail
        try:generic_objects.add(prop,parent,rig['root'])
        except RuntimeError as exc:assert str(exc)=='Intentional construction failure'
        else:raise AssertionError('Expected construction failure')
        finally:generic_objects.ensure_controller=real_ensure
        assert c.objExists(prop+'.genericSpaceOwner') and not c.listConnections(prop+'.genericSpaceOwner')
        assert not c.listRelatives(prop,p=True)
        assert max(abs(a-b) for a,b in zip(pose,c.xform(prop,q=True,ws=True,m=True)))<1e-5
        row=generic_objects.add(prop,parent,rig['root'])
        assert c.objExists(row['control']) and c.listConnections(prop+'.genericSpaceOwner')==[row['owner']]
        assert keys==(c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True))
        for target in (prop,row['control']):
            try:generic_objects.add(target,parent,rig['root'])
            except ValueError:pass
            else:raise AssertionError('Duplicate not rejected')
        c.disconnectAttr(row['owner']+'.message',prop+'.genericSpaceOwner')
        try:generic_objects.add(prop,parent,rig['root'])
        except ValueError:pass
        else:raise AssertionError('Metadata-only registration not rejected')
        report.update(passed=True,stale_marker_reused=True,failure_rollback=True,animation_preserved=True,duplicates_rejected=True)
    except Exception:report.update(passed=False,traceback=traceback.format_exc())
    finally:
        generic_objects.ensure_controller=real_ensure
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
