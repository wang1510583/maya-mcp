"""Space switches must persist on reevaluation, not just match once."""
import json, traceback
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs.integrated import builder, generic_objects
from maya_agent.rigs import arm_ik, switch_panel

def run():
    ns='genericTimelineTest'; assert not c.namespace(exists=ns)
    selection=c.ls(sl=True,l=True); frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True); modified=c.file(q=True,modified=True)
    before=set(c.ls(uuid=True)); owned=[ns]; report={}
    def world(n): return c.xform(n,q=True,ws=True,m=True)
    def err(a,b): return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False); c.currentTime(0); c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist')
        finger=c.createNode('joint',name=ns+':finger',parent=wrist); c.setAttr(finger+'.tx',3)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig')
        owned += [rig['namespace'],rig['parts']['hand_L']['namespace']]
        parent=c.createNode('transform',name=ns+':parent')
        prop=c.createNode('transform',name=ns+':prop'); c.setAttr(prop+'.translate',5,3,2)
        c.setKeyframe(prop,at='tx',t=0,v=5)
        for attr,value in [('tx',20),('ry',60)]:
            c.setKeyframe(parent,at=attr,t=0,v=0); c.setKeyframe(parent,at=attr,t=10,v=value)
        row=generic_objects.add(prop,parent,rig['root']); mode=row['global_plug']
        control_curve=c.listConnections(row['control']+'.tx',s=True,d=False,type='animCurve')[0]
        control_keys=(c.keyframe(control_curve,q=True,tc=True),c.keyframe(control_curve,q=True,vc=True))
        for t in (0,2): c.setKeyframe(mode,t=t,v=0,ott='step')
        panel=switch_panel.build(rig['root']); handle=panel['sliders']['generic_1']
        c.autoKeyframe(state=True)
        # Reuse the destination after earlier switch keys, like the live scene.
        for t in (1,2,3):
            c.currentTime(t)
            switch_panel.apply(handle,1,key=True)
            switch_panel.apply(handle,0,key=True)
        # Editing/deleting mode keys on the public panel leaves old hidden
        # matching keys behind. There is no switch at frame 3 any longer.
        c.cutKey(mode,time=(1,1),clear=True); c.cutKey(mode,time=(3,3),clear=True)
        c.currentTime(2); pose=world(prop)
        switch_panel.apply(handle,1,key=True)
        report['mode_keys']={'times':c.keyframe(mode,q=True,tc=True),'values':c.keyframe(mode,q=True,vc=True)}
        report['immediate_mode']=c.getAttr(mode); report['immediate_error']=err(pose,world(prop))
        report['samples']=[]
        for t in (2.5,3,5,10,2,0):
            c.currentTime(t); report['samples'].append(dict(frame=t,mode=c.getAttr(mode),error=err(pose,world(prop))))
        assert report['immediate_mode']==1,report
        assert all(s['mode']==1 and s['error']<1e-5 for s in report['samples'] if s['frame']>=2),report
        assert report['samples'][-1]['mode']==0,report
        # A later deliberately authored switch and its matching pose survive.
        c.currentTime(6);switch_panel.apply(handle,0,key=True)
        c.currentTime(8);switch_panel.apply(handle,1,key=True)
        c.currentTime(9);later=world(prop)
        future_keys={p:(c.keyframe(p,q=True,time=(6,100),tc=True),c.keyframe(p,q=True,time=(6,100),vc=True))
                     for p in [mode]+[n+'.'+a for n in row['offsets'] for a in ('tx','ty','tz','rx','ry','rz')]}
        c.currentTime(2);switch_panel.apply(handle,0,key=True);switch_panel.apply(handle,1,key=True)
        for p,keys in future_keys.items():
            assert keys==(c.keyframe(p,q=True,time=(6,100),tc=True),c.keyframe(p,q=True,time=(6,100),vc=True)),p
        c.currentTime(9);assert err(later,world(prop))<1e-5
        c.currentTime(4); held=om.MMatrix(world(prop));master=row['master'];initial=om.MMatrix(world(master))
        c.setAttr(master+'.translate',3,-2,4);c.setAttr(master+'.rotate',17,-31,12)
        expected=held*initial.inverse()*om.MMatrix(world(master))
        report['master_error']=err(list(expected),world(prop));assert report['master_error']<1e-5
        assert control_keys==(c.keyframe(control_curve,q=True,tc=True),c.keyframe(control_curve,q=True,vc=True))
        report['future_switches_preserved']=True;report['control_animation_preserved']=True
        report['passed']=True
    except Exception: report.update(passed=False,traceback=traceback.format_exc())
    finally:
        for n in owned:
            nodes=c.ls(n+':*',type='constraint') or []
            if nodes:c.delete(nodes)
        for n in reversed(owned):
            if c.namespace(exists=n):
                nodes=c.ls(n+':*') or []
                if nodes:c.delete(nodes)
                c.namespace(removeNamespace=n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(cl=True)
        c.file(modified=modified);arm_ik.install();switch_panel.install()
        report['original_nodes_retained']=before.issubset(set(c.ls(uuid=True)))
    return report
