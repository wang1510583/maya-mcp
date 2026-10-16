"""Legacy upgrade and native manipulator/animation regression; disposable only."""
import importlib,json,traceback
import maya.cmds as c
from maya_agent.rigs.integrated import builder,generic_objects
from maya_agent.rigs import switch_panel,arm_ik
for module in (builder,generic_objects,switch_panel):importlib.reload(module)

def run():
    ns='genericBoxTest';assert not c.namespace(exists=ns)
    selected=c.ls(sl=True,l=True);frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True);modified=c.file(q=True,modified=True)
    before=set(c.ls(uuid=True));owned=[ns];results={};real_ensure=generic_objects.ensure_controller
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False);c.namespace(add=ns)
        wrist=c.createNode('joint',name=ns+':wrist');finger=c.createNode('joint',name=ns+':finger',parent=wrist);c.setAttr(finger+'.tx',2)
        rig=builder.build({'hand_L':dict(targets=[finger])},namespace=ns+'Rig');owned += [rig['namespace'],rig['parts']['hand_L']['namespace']]
        parent=c.createNode('transform',name=ns+':parent');c.setAttr(parent+'.rotate',13,27,-19)
        for kind in ('joint','mesh'):
            prop=c.createNode('joint',name=ns+':jointProp') if kind=='joint' else c.polyCube(name=ns+':meshProp',ch=False)[0]
            c.setAttr(prop+'.translate',7,4,8);c.setAttr(prop+'.rotateOrder',4)
            c.setAttr(prop+'.rotatePivot',.3,-.2,.5);c.setAttr(prop+'.rotateAxis',4,-7,11)
            if kind=='joint':c.setAttr(prop+'.jointOrient',27,-34,16)
            c.setAttr(prop+'.offsetParentMatrix',1,0,0,0,0,1,0,0,0,0,1,0,.5,-.1,.2,1,type='matrix')
            child=c.createNode('transform',name=ns+':'+kind+'Child',parent=prop);c.setAttr(child+'.tx',3)
            c.setKeyframe(prop,at='tx',t=0,v=7);c.setKeyframe(prop,at='tx',t=10,v=12)
            c.setKeyframe(prop,at='ry',t=0,v=9);c.setKeyframe(prop,at='ry',t=10,v=42)
            curves=c.listConnections(prop,s=True,d=False,type='animCurve') or []
            curve_data={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyTangent(n,q=True,ott=True)) for n in curves}
            # Construct exactly the previous version's prop and panel first.
            generic_objects.ensure_controller=lambda character,owner,**kwargs:generic_objects._data(owner)
            c.currentTime(0);row=generic_objects.add(prop,parent,rig['root']);panel=switch_panel.build(rig['root'])
            generic_objects.ensure_controller=real_ensure
            target=c.ls(row['target_uuid'],l=True)[0];source_parent=c.listRelatives(target,p=True,f=True)
            samples={}
            for f in (0,2.5,5,7.5,10):
                c.currentTime(f);samples[f]=(world(target),world(child))
            c.currentTime(0)
            # Refresh upgrades the old object and rewires the existing slider.
            handle=panel['sliders']['generic_'+str(row['number'])]
            refreshed=switch_panel.build(rig['root']);new=generic_objects._data(row['owner']);control=new['control']
            assert handle==refreshed['sliders']['generic_'+str(row['number'])]
            assert c.listRelatives(target,p=True,f=True)==source_parent
            shapes=c.listRelatives(control,s=True,f=True) or []
            assert len(shapes)==1 and c.nodeType(shapes[0])=='nurbsCurve'
            assert c.getAttr(shapes[0]+'.degree')==1 and c.getAttr(shapes[0]+'.spans')==15
            worst=0
            for f,(m,child_m) in samples.items():
                c.currentTime(f);worst=max(worst,error(world(target),m),error(world(control),m),error(world(child),child_m))
            assert worst<1e-5,worst
            for n,expected in curve_data.items():
                assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyTangent(n,q=True,ott=True))==expected
            assert c.connectionInfo(handle+'.control_translateX',sfd=True).split('.')[0].rsplit('|',1)[-1]==control.rsplit('|',1)[-1]
            c.currentTime(0);start=c.xform(target,q=True,ws=True,rp=True)
            c.move(1,2,-3,control,r=True,ws=True)
            end=c.xform(target,q=True,ws=True,rp=True)
            assert max(abs((b-a)-d) for a,b,d in zip(start,end,(1,2,-3)))<1e-5
            c.rotate(11,-17,23,control,r=True,ws=True)
            assert error(world(control),world(target))<1e-5
            for value in (1,0):
                pose=world(target);generic_objects.switch(row['owner'],value,key=False)
                assert error(pose,world(target))<1e-5
                assert error(world(control),world(target))<1e-5
            c.currentTime(6);c.setKeyframe(handle)
            assert 6 in c.keyframe(control+'.tx',q=True,tc=True)
            count=len(c.ls(rig['namespace']+':*'));switch_panel.build(rig['root']);assert len(c.ls(rig['namespace']+':*'))==count
            if kind=='mesh':assert c.getAttr(c.listRelatives(target,s=True,f=True)[0]+'.lodVisibility')
            results[kind]=dict(animation_error=worst,native_move_rotate=True,mode_switch=True,panel_keys=True,curve_values_preserved=True)
        results['passed']=True
    except Exception:results.update(passed=False,traceback=traceback.format_exc())
    finally:
        generic_objects.ensure_controller=real_ensure
        for name in owned:
            nodes=c.ls(name+':*',type='constraint') or []
            if nodes:c.delete(nodes)
        # Prop animations now belong to controls in the rig namespace; these
        # are all fixture nodes and no user's namespace is involved.
        for name in reversed(owned):
            if c.namespace(exists=name):
                nodes=c.ls(name+':*') or []
                if nodes:c.delete(nodes)
                c.namespace(removeNamespace=name)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selected,r=True) if selected else c.select(cl=True)
        c.file(modified=modified);arm_ik.install();switch_panel.install()
        results['original_nodes_retained']=before.issubset(set(c.ls(uuid=True)))
    return results

result=run()
