"""Disposable comparisons; never modifies the user's reference rig."""
import uuid
import math
import maya.cmds as c
import maya.mel as mel
import runpy


def run(key_edits=True,spaces=False):
    from maya_agent.rigs.soft_limb import build,build_from_selection
    from maya_agent.rigs.soft_leg import cleanup
    before=set(c.ls(long=True));selected=c.ls(sl=True,long=True) or [];time=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    namespaces=[];results=[];assemblies=[]
    try:
        for mode in ('template','fit','animation','integrated','integrated_animation'):
            ns='_alignDebug_'+uuid.uuid4().hex[:7]
            if mode.startswith('integrated'):
                suite=runpy.run_path('D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/test_integrated_rig_live.py')
                _,parts=suite['fixture'](ns,mode.endswith('animation'),shoulders=True)
                if spaces:
                    for p in parts.values():p.update(space_chest=True,space_head=True,space_upper_arm=True,space_wrist=True,space_foot=True)
                from maya_agent.rigs.integrated import build as assembly
                full=assembly(parts,namespace=ns);assemblies.append(full)
                rig=full['parts']['arm_L'];ns=rig['namespace']
            elif mode=='template':
                namespaces.append(ns);rig=build(ns)
            else:
                namespaces.append(ns)
                targets=[]
                for i,p in enumerate([(0,10,0),(6,12,0),(10,10,0)]):
                    n=c.createNode('transform',name=ns+'_target'+str(i));c.xform(n,ws=True,t=p);targets.append(n)
                rig=build_from_selection(targets,namespace=ns,copy_animation=mode=='animation',start_frame=time,end_frame=time+2)
            fk=rig['controls']['middle_fk'];controls=[rig['controls'][k] for k in ('shoulder_fk','middle_fk','end_fk')]
            bases=[ns+':base_L'+str(i) for i in (1,2,3)]
            for attr,delta in [('translateX',1),('translateY',.5),('rotateX',25),('rotateY',15),('rotateZ',-35)]:
                value=c.getAttr(fk+'.'+attr)+delta
                if mode.endswith('animation') and key_edits:c.setKeyframe(fk,at=attr,t=time,v=value);c.dgdirty(fk)
                else:c.setAttr(fk+'.'+attr,value)
            nodes=rig['joints']+[m['target'] for m in rig.get('target_mapping',[])]
            pre={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
            ref=[c.xform(n,q=True,ws=True,m=True) for n in bases]
            c.select(fk,r=True)
            try:mel.eval('kurok_recalculate_system(0);');failure=None
            except Exception as exc:failure=str(exc)
            errors={n:max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))) for n,m in pre.items()}
            align=[max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))) for n,m in zip(controls,ref)]
            results.append(dict(mode=mode,failure=failure,errors=errors,alignment=align,
                pole=c.xform(ns+':elb_L1',q=True,ws=True,t=True),reference_pole=c.xform(ns+':locator3',q=True,ws=True,t=True)))
        return results
    finally:
        for full in assemblies:suite['remove'](full)
        for ns in namespaces:
            for n in c.ls(ns+':*',type='constraint') or []:
                if c.objExists(n):c.delete(n)
            if c.namespace(exists=ns):cleanup(ns)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.autoKeyframe(state=auto);c.select(selected,r=True) if selected else c.select(clear=True)
        assert set(c.ls(long=True))==before
