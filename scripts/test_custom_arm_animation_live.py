"""Animation transfer regression on owned fixtures; never replace the user's scene."""
import json
import math
import uuid
import maya.cmds as c
from maya_agent.rigs.soft_limb import build_from_selection as build
from maya_agent.rigs.custom_body.animation import frame_range
from maya_agent.rigs.soft_limb.animation import Transfer
from maya_agent.rigs.custom_body.targets import CHANNELS


def run_case(count=3, chain=True, fail=False, spin=False, scale_animation=False, shifted_pivots=False):
    before = set(c.ls(long=True))
    selected, time = c.ls(selection=True, long=True) or [], c.currentTime(query=True)
    dirty = c.file(query=True, modified=True)
    prefix = '_ARM_ANIM_' + uuid.uuid4().hex[:8]
    rig = None
    frames = frame_range(1.25, 12.75, .5)
    def world(n):
        return c.xform(n, query=True, worldSpace=True, matrix=True)
    def near(a,b):
        error = max(abs(x-y) for x,y in zip(a,b))
        assert error < 1e-4, error
        return error
    try:
        root = c.createNode('transform', name=prefix+'_root')
        c.setAttr(root+'.scale', 1.5,1.5,1.5)
        nodes=[]
        for i in range(count):
            node=c.createNode('joint' if chain else 'transform', name=prefix+'_t'+str(i),
                              parent=nodes[-1] if chain and nodes else root)
            c.setAttr(node+'.rotateOrder', i%6)
            if chain: c.setAttr(node+'.jointOrient', 10,20,5)
            c.xform(node,worldSpace=True,translation=(30+i*.4,3+i*2+i*i*.1,math.sin(i)),rotation=(i*4,15-i*2,i*7))
            nodes.append(c.ls(node,long=True)[0])
            if shifted_pivots and not chain:c.setAttr(node+'.rotatePivot',.3,-.2,.15)
        mesh=None
        if chain and count==3:
            mesh=c.polyCube(name=prefix+'_mesh', constructionHistory=False)[0]
            c.xform(mesh,worldSpace=True,translation=(31,7,0))
            c.skinCluster(nodes,mesh,toSelectedBones=True,name=prefix+'_skin')
        for i,node in enumerate([root]+nodes):
            for attr,delta in (('translateX',1.2+i*.15),('rotateY',35+i*2),('rotateZ',(240 if spin else 25)+i)):
                base=c.getAttr(node+'.'+attr)
                for f,v in ((-10,base-3),(1.25,base),(7.25,base+delta),(12.75,base-delta*.5),(30,base+10)):
                    c.setKeyframe(node,attribute=attr,time=f,value=v,inTangentType='auto',outTangentType='auto')
        scale_edges={}
        if scale_animation:
            for i,node in enumerate([root]+nodes):
                base=c.getAttr(node+'.scaleX')
                for axis in 'XYZ':
                    for f,value in ((1.25,base),(7.25,base*1.2),(12.75,base*.9)):
                        c.setKeyframe(node,at='scale'+axis,t=f,v=value)
                    plug=node+'.scale'+axis
                    scale_edges[plug]=c.connectionInfo(plug,sourceFromDestination=True)
        curves=list(set(c.listConnections(nodes+[root],source=True,destination=False,type='animCurve') or []))
        original={curve:(c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True),
                         c.keyTangent(curve,q=True,itt=True),c.keyTangent(curve,q=True,ott=True)) for curve in curves}
        edges={n+'.'+a:c.connectionInfo(n+'.'+a,sourceFromDestination=True) for n in nodes for a in CHANNELS}
        motion=[]
        for f in frames:
            c.currentTime(f)
            motion.append(([world(n) for n in nodes], c.xform(mesh+'.vtx[*]',q=True,ws=True,t=True) if mesh else None))
        construction_frame = -3.7 if spin else time
        c.currentTime(construction_frame)
        fixture=set(c.ls(long=True))
        previous=Transfer.bake
        if fail:
            def injected(self,mappings):
                previous(self,mappings)
                raise RuntimeError('injected after baking')
            Transfer.bake=injected
        try:
            try:
                rig=build(namespace=prefix,targets=nodes,copy_animation=True,start_frame=frames[0],end_frame=frames[-1],sample_step=.5)
                assert not fail
            except RuntimeError as exc:
                if not fail or 'injected after baking' not in str(exc): raise
                assert set(c.ls(long=True))==fixture
                assert all(c.connectionInfo(dst,sourceFromDestination=True)==src for dst,src in edges.items())
        finally:
            Transfer.bake=previous
        assert c.currentTime(q=True)==construction_frame
        error=0
        for f,(matrices,verts) in reversed(list(zip(frames,motion))):
            c.currentTime(f)
            for n,expected in zip(nodes,matrices): error=max(error,near(world(n),expected))
            if mesh: near(c.xform(mesh+'.vtx[*]',q=True,ws=True,t=True),verts)
        for curve,values in original.items():
            assert (c.keyframe(curve,q=True,tc=True),c.keyframe(curve,q=True,vc=True),
                    c.keyTangent(curve,q=True,itt=True),c.keyTangent(curve,q=True,ott=True)) == values
        if rig:
            import maya.mel as mel
            c.currentTime(frames[5])
            poses=[world(n) for n in nodes]
            c.select(rig['controls']['middle_fk'],r=True)
            mel.eval('kurok_recalculate_system(0);')
            for n,m in zip(nodes,poses):near(world(n),m)
            assert not c.ls(prefix+':capture*')
            assert not (set(c.ls(type='pairBlend'))-before)
            backup=rig['animation_transfer']['source_animation_backup']
            assert set(c.listConnections(backup+'.sourceCurves',s=True,d=False) or [])==set(src.split('.')[0] for src in edges.values() if src)
            assert all(not c.isConnected(src,dst) for dst,src in edges.items() if src)
        assert all(c.isConnected(src,dst) for dst,src in scale_edges.items())
        return {'count':count,'joint_chain':chain,'rollback':fail,'passed':True,'max_error':error,
                'samples':len(frames),'skin_checked':bool(mesh),'scale_curves_preserved':len(scale_edges),
                'shifted_pivots':shifted_pivots}
    finally:
        # Only nodes born inside this fixture are eligible for removal.
        for n in reversed(c.ls(long=True)):
            if n not in before and c.objExists(n): c.delete(n)
        if c.namespace(exists=prefix): c.namespace(removeNamespace=prefix)
        c.currentTime(time)
        c.select(selected,r=True) if selected else c.select(clear=True)
        assert set(c.ls(long=True))==before
        c.file(modified=dirty)
