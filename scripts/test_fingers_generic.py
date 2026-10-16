"""Run in Maya; disposable DAG only, never opens or saves a scene."""
import importlib,json,traceback
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs import integrated,fingers,zero_channels,arm_ik,switch_panel
from maya_agent.rigs.integrated import builder,master_control,generic_objects
for module in (integrated,fingers,zero_channels,master_control,builder,generic_objects,arm_ik,switch_panel):importlib.reload(module)

def run():
    before=set(c.ls(uuid=True));selected=c.ls(sl=True,l=True) or [];frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    modified=c.file(q=True,modified=True);results={};owned=[]
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        c.autoKeyframe(state=False)
        for side,lengths in [('L',[3]*5),('R',[1,2,4,3,2,1])]:
            ns='fingerFeatureTest'+side
            assert not c.namespace(exists=ns)
            c.namespace(add=ns);owned.append(ns)
            wrist=c.createNode('joint',name=ns+':wrist');c.setAttr(wrist+'.translate',10,20,3)
            chains=[]
            for i,length in enumerate(lengths):
                chain=[];parent=wrist
                for j in range(length):
                    node=c.createNode('joint',name=ns+':f%d_j%d'%(i,j),parent=parent)
                    c.setAttr(node+'.translate',2,i*1.5 if j==0 else 0,0);chain.append(node);parent=node
                chains.append(chain)
            names=[chain[j] for j in range(max(lengths)) for chain in chains if j<len(chain)]
            for n in [wrist]+names:
                c.setKeyframe(n,at='rz',t=0,v=0);c.setKeyframe(n,at='rz',t=4,v=12 if n!=wrist else 20)
            c.currentTime(0);expected={}
            for f in range(5):
                c.currentTime(f);expected[f]=[world(n) for n in names]
            c.currentTime(0)
            rig=builder.build({'hand_'+side:dict(targets=names,copy_animation=True,start_frame=0,end_frame=4)},namespace=ns+'Rig',zero_controls=True)
            owned.extend([rig['namespace'],rig['parts']['hand_'+side]['namespace']])
            part=rig['parts']['hand_'+side]
            assert list(map(len,part['chains']))==lengths
            max_error=0
            for f in range(5):
                c.currentTime(f)
                max_error=max(max_error,max(error(world(n),m) for n,m in zip(names,expected[f])))
            assert max_error<1e-4,max_error
            c.currentTime(0);c.setAttr(wrist+'.tx',15)
            assert abs(world(names[0])[12]-expected[0][0][12]-5)<1e-5
            ctrl=part['controls']['finger01_01'];c.cutKey(ctrl,at='rz',clear=True);c.setAttr(ctrl+'.rz',35)
            assert error(world(names[0]),expected[0][0])>1
            results['hand_'+side]=dict(lengths=lengths,animation_error=max_error,wrist_follow=True)
            if side=='L':test_rig=rig
        # Append to an existing arm, then compare FK/IK and master deltas.
        ns='fingerFeatureArm';assert not c.namespace(exists=ns);c.namespace(add=ns);owned.append(ns)
        joints=[];parent=None
        for name,pos in [('shoulder',(0,20,0)),('elbow',(8,18,2)),('wrist',(14,20,0))]:
            n=c.createNode('joint',name=ns+':'+name,**({'parent':parent} if parent else {}))
            c.xform(n,ws=True,t=pos);joints.append(n);parent=n
        finger=[]
        for i in range(3):
            n=c.createNode('joint',name=ns+':finger'+str(i),parent=parent);c.setAttr(n+'.tx',2);finger.append(n);parent=n
        rig=builder.build({'arm_L':dict(targets=joints,space_wrist=True)},namespace=ns+'Rig',zero_controls=True)
        owned.extend([rig['namespace'],rig['parts']['arm_L']['namespace']])
        original_arm=rig['parts']['arm_L']['root']
        appended=fingers.append(rig['root'],{'hand_L':dict(targets=finger)})
        owned.extend([appended['parts']['hand_L']['namespace'].rsplit('_hand_L',1)[0],appended['parts']['hand_L']['namespace']])
        assert appended['parts']['arm_L']['root']==original_arm
        follow_errors=[]
        for mode in (0,1):
            arm_ik.switch(original_arm,mode,key=False)
            base={n:om.MMatrix(world(n)) for n in finger}
            master=rig['master_control'];c.setAttr(master+'.translate',3,-2,4);c.setAttr(master+'.rotate',17,21,-14)
            delta=om.MMatrix(world(master))
            e=max(error(world(n),list(m*delta)) for n,m in base.items());follow_errors.append(e);assert e<1e-4,e
            c.setAttr(master+'.translate',0,0,0);c.setAttr(master+'.rotate',0,0,0)
        ik=json.loads(c.getAttr(original_arm+'.armWorldIKData'))
        wrist=ik['controls']['wrist'];local=om.MMatrix(world(finger[0]))*om.MMatrix(world(joints[-1])).inverse()
        c.setAttr(wrist+'.tx',c.getAttr(wrist+'.tx')+3)
        assert error(world(finger[0]),list(local*om.MMatrix(world(joints[-1]))))<1e-4
        results['append_arm']=dict(master_errors=follow_errors,ik_wrist_follow=True)
        # Props use a separate root under the disposable character.
        ns=test_rig['namespace'];root=test_rig['root'];master=test_rig['master_control']
        parent=c.createNode('transform',name=ns+':propParent',parent=root);c.setAttr(parent+'.tx',6)
        prop=c.createNode('transform',name=ns+':prop');c.setAttr(prop+'.translate',3,5,7)
        child=c.createNode('transform',name=ns+':child',parent=prop);c.setAttr(child+'.ty',2)
        c.setKeyframe(prop,at='rx',t=0,v=0);c.setKeyframe(prop,at='rx',t=4,v=30)
        initial=world(prop);row=generic_objects.add(prop,parent,root);prop=c.ls(row['target_uuid'],l=True)[0]
        assert error(initial,world(prop))<1e-5
        c.setAttr(parent+'.tx',11);assert abs(world(prop)[12]-initial[12]-5)<1e-5
        relative=om.MMatrix(world(prop))*om.MMatrix(world(parent)).inverse()
        c.setAttr(parent+'.rotate',17,-23,11)
        assert error(world(prop),list(relative*om.MMatrix(world(parent))))<1e-5
        before_switch=world(prop);generic_objects.switch(row['owner'],1,key=False)
        assert error(before_switch,world(prop))<1e-5
        c.setAttr(parent+'.tx',16);assert error(before_switch,world(prop))<1e-5
        c.setAttr(master+'.tz',8);assert abs(world(prop)[14]-before_switch[14]-8)<1e-5
        relative=om.MMatrix(world(prop))*om.MMatrix(world(master)).inverse()
        c.setAttr(master+'.rotate',-13,19,31)
        assert error(world(prop),list(relative*om.MMatrix(world(master))))<1e-5
        for f,value in [(1,0),(2,1),(3,0),(4,1)]:
            c.currentTime(f);old=world(prop);generic_objects.switch(row['owner'],value,key=True)
            assert error(old,world(prop))<1e-5
        assert {1,2,3,4}.issubset(c.keyframe(row['global_plug'],q=True,tc=True))
        panel=switch_panel.build(root);old=panel['sliders']['generic_1']
        prop2=c.createNode('transform',name=ns+':prop2');generic_objects.add(prop2,parent,root)
        refreshed=switch_panel.build(root)
        assert refreshed['sliders']['generic_1']==old and 'generic_2' in refreshed['sliders']
        count=len(c.ls(ns+':*'));switch_panel.build(root);assert len(c.ls(ns+':*'))==count
        results['generic']=dict(parent_follow=True,master_follow=True,matched_switch=True,refresh_two=True,idempotent=True)
        results['passed']=True
    except Exception:
        results['passed']=False;results['traceback']=traceback.format_exc()
    finally:
        # Only namespaces reserved by this test. Constraints first protect source DAG.
        for ns in owned:
            constraints=c.ls(ns+':*',type='constraint') or []
            if constraints:c.delete(constraints)
        for ns in reversed(owned):
            if c.namespace(exists=ns):
                nodes=c.ls(ns+':*',long=True) or []
                if nodes:c.delete(nodes)
                c.namespace(removeNamespace=ns)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selected,r=True) if selected else c.select(cl=True)
        c.file(modified=modified)
        arm_ik.install();switch_panel.install()
        results['original_nodes_retained']=before.issubset(set(c.ls(uuid=True)))
    return results

result=run()
