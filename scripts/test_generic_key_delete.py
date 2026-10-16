"""Deleting public timeline frames must delete space matching keys natively."""
import json,traceback
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs.integrated import builder,generic_objects,generic_keys
from maya_agent.rigs import arm_ik,switch_panel

def run(history=False):
    ns='genericKeyDeleteTest';assert not c.namespace(exists=ns)
    selection=c.ls(sl=True,l=True);frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    before=set(c.ls(uuid=True));owned=[ns];report={}
    def world(n):return om.MMatrix(c.xform(n,q=True,ws=True,m=True))
    def err(a,b):return max(abs(x-y) for x,y in zip(a,b))
    def keys(plugs):return {p:[c.keyframe(p,q=True,tc=True),c.keyframe(p,q=True,vc=True)] for p in plugs}
    try:
        c.autoKeyframe(state=False);c.currentTime(0);c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist');finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',3)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig');owned += [rig['namespace'],rig['parts']['hand_L']['namespace']]
        parent=c.createNode('transform',name=ns+':parent');prop=c.createNode('transform',name=ns+':prop');c.setAttr(prop+'.tx',5)
        c.setKeyframe(parent,at='tx',t=0,v=0);c.setKeyframe(parent,at='tx',t=10,v=25)
        row=generic_objects.add(prop,parent,rig['root']);panel=switch_panel.build(rig['root']);handle=panel['sliders']['generic_1']
        plugs=[row['global_plug']]+[n+'.'+a for n in row['offsets'] for a in generic_keys.TR]
        c.currentTime(2);c.setKeyframe(handle)
        baseline=world(prop)*world(parent).inverse()
        c.currentTime(3);generic_objects.switch(row['owner'],1,key=True)
        c.currentTime(7);generic_objects.switch(row['owner'],0,key=True)
        original=keys(plugs)
        c.cutKey(handle,time=(3,7),clear=True)
        assert all(not (3<=t<=7) for p in plugs for t in c.keyframe(p,q=True,tc=True) or [])
        if history:
            c.undo();assert keys(plugs)==original
            c.redo();assert all(not (3<=t<=7) for p in plugs for t in c.keyframe(p,q=True,tc=True) or [])
        worst=0
        for t in (2,2.9,3,3.1,6.9,7,7.1,10):
            c.currentTime(t);worst=max(worst,err(world(prop),baseline*world(parent)))
        assert worst<1e-5,worst
        # Legacy deletion edited only the mode; explicit repair retains TR.
        c.currentTime(3);generic_objects.switch(row['owner'],1,key=True)
        c.currentTime(7);generic_objects.switch(row['owner'],0,key=True)
        c.cutKey(row['global_plug'],time=(3,7),clear=True)
        control_keys=keys([row['control']+'.'+a for a in generic_keys.TR])
        cleaned=generic_keys.clean_orphan_matches(row['owner'])
        assert cleaned['removed_frames']==[3.0,7.0]
        assert control_keys==keys(list(control_keys))
        if history:
            c.undo();assert 7 in c.keyframe(row['offsets'][0]+'.tx',q=True,tc=True)
            c.redo();assert 7 not in c.keyframe(row['offsets'][0]+'.tx',q=True,tc=True)
        # Deleting a single frame from the box also reaches hidden matches.
        c.currentTime(3);generic_objects.switch(row['owner'],1,key=True)
        c.cutKey(row['control'],time=(3,3),clear=True)
        assert all(3 not in (c.keyframe(p,q=True,tc=True) or []) for p in plugs)
        c.cutKey(handle,time=(-100,100),clear=True)
        assert all(not c.keyframe(p,q=True,kc=True) for p in plugs)
        report=dict(passed=True,panel_range_delete=True,control_frame_delete=True,delete_all=True,
                    no_jump_error=worst,legacy_cleanup=True,control_keys_preserved=True,undo_redo=history)
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
