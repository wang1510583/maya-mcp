"""Animation, skin and rollback verification on disposable four-point fixtures."""
import math
import uuid
import maya.cmds as c


def run_case(chain=True,side='L',fail=False,shifted_pivots=False):
    from maya_agent.rigs.soft_leg import build_from_selection,cleanup
    from maya_agent.rigs.soft_leg.animation import Transfer
    from maya_agent.rigs.custom_body.animation import frame_range
    from maya_agent.rigs.custom_body.targets import CHANNELS
    before=set(c.ls(long=True))
    selected=c.ls(sl=True,long=True) or []
    time=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True)
    c.autoKeyframe(state=False)
    prefix='_LEG_ANIM_'+uuid.uuid4().hex[:8]
    rig=None
    frames=frame_range(1.25,8.75,.5)
    original_bake=Transfer.bake
    def world(n):return c.xform(n,q=True,ws=True,m=True)
    def near(a,b):
        error=max(abs(x-y) for x,y in zip(a,b));assert error<1e-4,error
        return error
    try:
        root=c.createNode('transform',name=prefix+'_root')
        c.setAttr(root+'.scale',1.5,1.5,1.5)
        nodes=[]
        for i,point in enumerate([(30,14,0),(30,8,1),(30,2,0),(30,.4,3)]):
            n=c.createNode('joint' if chain else 'transform',name=prefix+'_target'+str(i),parent=nodes[-1] if chain and nodes else root)
            c.setAttr(n+'.rotateOrder',i%6)
            if chain:c.setAttr(n+'.jointOrient',10,20,5)
            c.xform(n,ws=True,t=point,rotation=(i*4,15-i*2,i*7))
            if shifted_pivots:c.setAttr(n+'.rotatePivot',.1,.15,-.05)
            nodes.append(c.ls(n,long=True)[0])
        mesh=None
        if chain:
            mesh=c.polyCube(name=prefix+'_mesh',constructionHistory=False)[0]
            c.xform(mesh,ws=True,t=(30,7,1))
            c.skinCluster(nodes,mesh,toSelectedBones=True,name=prefix+'_skin')
        for i,n in enumerate([root]+nodes):
            for attr,delta in [('translateX',.3+i*.1),('rotateY',15+i*2),('rotateZ',10+i)]:
                base=c.getAttr(n+'.'+attr)
                for f,v in [(-5,base-1),(1.25,base),(4.75,base+delta),(8.75,base-delta*.2),(20,base+2)]:
                    c.setKeyframe(n,at=attr,t=f,v=v)
            for axis in 'XYZ':
                base=c.getAttr(n+'.scale'+axis)
                for f,v in [(1.25,base),(4.75,base*1.1),(8.75,base*.95)]:c.setKeyframe(n,at='scale'+axis,t=f,v=v)
        curves=set(c.listConnections(nodes+[root],s=True,d=False,type='animCurve') or [])
        original={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True)) for n in curves}
        edges={n+'.'+a:c.connectionInfo(n+'.'+a,sourceFromDestination=True) for n in nodes for a in CHANNELS}
        scales={n+'.scale'+a:c.connectionInfo(n+'.scale'+a,sourceFromDestination=True) for n in nodes+[root] for a in 'XYZ'}
        motion=[]
        for f in frames:
            c.currentTime(f)
            motion.append(([world(n) for n in nodes],[c.xform(n,q=True,ws=True,rp=True) for n in nodes],
                           c.xform(mesh+'.vtx[*]',q=True,ws=True,t=True) if mesh else None))
        c.currentTime(.75)
        fixture=set(c.ls(long=True))
        if fail:
            def injected(self,mappings):
                original_bake(self,mappings)
                raise RuntimeError('injected after leg baking')
            Transfer.bake=injected
        try:
            rig=build_from_selection(nodes,namespace=prefix,side=side,copy_animation=True,start_frame=frames[0],end_frame=frames[-1],sample_step=.5)
            assert not fail
        except RuntimeError as exc:
            if not fail or 'injected after leg baking' not in str(exc):raise
            assert set(c.ls(long=True))==fixture
            assert all(c.connectionInfo(dst,sourceFromDestination=True)==src for dst,src in edges.items())
        assert c.currentTime(q=True)==.75
        if rig:
            from maya_agent.rigs.soft_leg import set_adjustment_mode
            from maya_agent.rigs.soft_leg.adjustment import resolve
            set_adjustment_mode(rig,True)
            _,setup=resolve(rig)
            for guide in setup['guides'].values():c.move(.12,.1,.25,guide,r=True,ws=True)
            set_adjustment_mode(rig,False)
        error=solver_error=0
        for f,(matrices,points,verts) in reversed(list(zip(frames,motion))):
            c.currentTime(f)
            for n,m in zip(nodes,matrices):error=max(error,near(world(n),m))
            if mesh:near(c.xform(mesh+'.vtx[*]',q=True,ws=True,t=True),verts)
            if rig:
                for j,p in zip(rig['joints'][:3],points[:3]):
                    actual=c.xform(j,q=True,ws=True,t=True)
                    delta=max(abs(a-b) for a,b in zip(actual,p))
                    assert delta<1e-4,(j,f,actual,p,delta,{k:c.xform(n,q=True,ws=True,rp=True) for k,n in rig['controls'].items()},dict(zip(rig['joints'],points)))
                    solver_error=max(solver_error,delta)
        for n,values in original.items():
            assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True))==values
        assert all(c.isConnected(src,dst) for dst,src in scales.items())
        if rig:
            assert not c.ls(prefix+':capture*') and not c.ls(prefix+':animationSolve*')
            assert rig['side']==side
            assert rig['controls']['foot']==prefix+':foot_'+side+'1'
        return dict(passed=True,joint_chain=chain,side=side,rollback=fail,shifted_pivots=shifted_pivots,
                    samples=len(frames),skin_checked=bool(mesh),scale_curves_preserved=len(scales),
                    max_error=error,max_solver_error=solver_error,animated_pivot_adjustment=bool(rig))
    finally:
        Transfer.bake=original_bake
        if rig:
            backup=rig['animation_transfer']['source_animation_backup']
            pairs=c.listConnections(backup+'.sourceCurves',s=True,d=False,p=True,c=True) or []
            for dst,src in zip(pairs[::2],pairs[1::2]):c.disconnectAttr(src,dst)
            cleanup(rig['namespace'])
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(selected,r=True) if selected else c.select(clear=True)
        assert set(c.ls(long=True))==before
