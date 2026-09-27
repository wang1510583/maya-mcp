"""Validate ground and raised foot pivots against a mesh with a known sole."""
import math
import runpy
import uuid
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

def verify(integrated=False,animated=False):
    from maya_agent.rigs.soft_leg import build_from_selection,cleanup
    from maya_agent.rigs.soft_leg.adjustment import resolve
    from maya_agent.rigs.integrated import build
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or []
    frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    c.autoKeyframe(state=False);rigs=[];prefix='_soleTest_'+uuid.uuid4().hex[:6]
    error=0
    try:
        for index,side in enumerate(('L','R')):
            root=c.createNode('transform',name=prefix+'_source'+str(index));targets=[]
            for i,point in enumerate([(0,15,0),(0,9,1),(0,3,0),(0,1,4)]):
                n=c.createNode('joint',name=prefix+'_joint'+str(index)+'_'+str(i),parent=targets[-1] if targets else root)
                c.xform(n,ws=True,t=point);targets.append(n)
            mesh=c.polyCube(w=2,h=1,d=8,ch=False,name=prefix+'_sole'+str(index))[0]
            c.xform(mesh,ws=True,t=(0,.5,2))
            skin=c.skinCluster(targets[2:],mesh,toSelectedBones=True)[0]
            c.skinPercent(skin,mesh,transformValue=[(targets[2],1),(targets[3],0)])
            bind=om.MMatrix(c.xform(targets[2],q=True,ws=True,m=True))
            if index:
                c.setAttr(root+'.translate',20,35,-10)
                c.setAttr(targets[2]+'.rotate',30,25,10)
            if animated:
                for f in (1,3,5):
                    c.setKeyframe(root,at='translateY',t=f,v=index*35+(f-1)*.5)
                    c.setKeyframe(targets[2],at='rotateX',t=f,v=index*30+(f-1)*2)
            frames=[1,2,3,4,5] if animated else [1];motion={}
            for f in frames:
                c.currentTime(f);motion[f]=[c.xform(n,q=True,ws=True,m=True) for n in targets]
            c.currentTime(1)
            delta=bind.inverse()*om.MMatrix(motion[1][2])
            expected={k:list(om.MPoint(p)*delta)[:3] for k,p in
                      {'heel':(0,0,-2),'toe_end':(0,0,6),'toe':(0,0,4)}.items()}
            if integrated:
                result=build({'leg_'+side:dict(targets=targets,copy_animation=animated,start_frame=1,end_frame=5)},
                             namespace=prefix+str(index))
                rig=result['parts']['leg_'+side];rigs.append((result,rig))
            else:
                rig=build_from_selection(targets,namespace=prefix+str(index),side=side,
                                         copy_animation=animated,start_frame=1,end_frame=5)
                rigs.append((None,rig))
            assert rig['pivot_placement']['method']=='skin_bind_sole'
            _,setup=resolve(rig)
            for key,point in expected.items():
                actual=c.xform(rig['controls'][key],q=True,ws=True,rp=True)
                assert math.dist(actual,point)<1e-5,(key,actual,point)
                assert math.dist(actual,c.xform(setup['guides'][key],q=True,ws=True,t=True))<1e-5
            for f,matrices in motion.items():
                c.currentTime(f)
                for node,matrix in zip(targets,matrices):
                    error=max(error,max(abs(a-b) for a,b in zip(matrix,c.xform(node,q=True,ws=True,m=True))))
            assert error<1e-4,error
        return dict(passed=True,integrated=integrated,animated=animated,sides=['L','R'],
                    grounded_and_raised_tilted_sole=True,world_error=error)
    finally:
        for result,rig in reversed(rigs):
            if result:suite['remove'](result)
            else:
                if rig.get('animation_transfer'):
                    backup=rig['animation_transfer']['source_animation_backup']
                    pairs=c.listConnections(backup+'.sourceCurves',s=True,d=False,p=True,c=True) or []
                    for dst,src in zip(pairs[::2],pairs[1::2]):c.disconnectAttr(src,dst)
                cleanup(rig['namespace'])
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before

