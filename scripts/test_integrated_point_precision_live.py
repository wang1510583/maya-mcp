"""Regression: float point attachments perturb almost-straight IK knees.

Run verify() inside Maya. Uses disposable fixtures; never opens/saves a scene.
Checks raw IK joint positions as well as target matrices, with unchanged 1e-4
tolerance. The decimal coordinates reproduce the reported frame-zero failure.
"""
import math
import runpy
import uuid
from pathlib import Path
import maya.cmds as c


POINTS = {
    'body': [(-.000002422333007,23.95581731796265,-.403852718767616),
             (.000005855827488,27.198022181944037,-.7179217366812913),
             (-.000002739146977,30.642762199586418,-.8208376732105749)],
    'leg_R': [(1.9898561334693514,23.95581916899772,-.4038515662539017),
              (2.808105967097597,15.844768815364285,.10626237128368471),
              (3.850964066326487,5.504304604336767,.7993649423999887),
              (3.8509620960134123,.11561765651567857,-1.3782244025814532)],
    'leg_L': [(-1.989851288805519,23.955813245628075,-.40385167876128975),
              (-2.8081019568524024,15.844771774282949,.10638274486984217),
              (-3.8509610709752673,5.504304474829826,.7993648959419146),
              (-3.8509648629762743,.11561873817642088,-1.3782250546249015)]}


def verify(animated=True):
    from maya_agent.rigs.integrated import builder
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));time=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True)
    prefix='_pointPrecision_'+uuid.uuid4().hex[:7];rig=None
    c.autoKeyframe(state=False)
    try:
        parts={};expected={};frames=list(range(5)) if animated else [0]
        for key,points in POINTS.items():
            nodes=[]
            for i,point in enumerate(points):
                n=c.createNode('transform',name=prefix+'_'+key+str(i));nodes.append(n)
                c.xform(n,ws=True,t=point)
                if animated:
                    for f in frames:
                        # Start near-straight, then bend and move both legs.
                        values=[point[0]+f*.13,point[1],point[2]+(f*.2 if i==1 else 0)]
                        for a,v in zip('XYZ',values):c.setKeyframe(n,at='translate'+a,t=f,v=v)
            parts[key]=dict(targets=nodes,copy_animation=animated,start_frame=0,end_frame=4,
                            space_foot=True,space_knee=True)
        for f in frames:
            c.currentTime(f)
            expected[f]={n:c.xform(n,q=True,ws=True,m=True) for p in parts.values() for n in p['targets']}
        c.currentTime(0)
        rig=builder.build(parts,namespace=prefix,create_master=False)
        def errors():
            target_error=0.;joint_error=0.
            for f in frames:
                c.currentTime(f)
                for n,m in expected[f].items():
                    target_error=max(target_error,max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))))
                for side in ('L','R'):
                    part=rig['parts']['leg_'+side]
                    assert len(c.listConnections(part['namespace']+':recalculate_node',s=True,d=False,p=True))==13
                    for joint,target in zip(part['joints'][:3],parts['leg_'+side]['targets'][:3]):
                        joint_error=max(joint_error,math.dist(c.xform(joint,q=True,ws=True,t=True),expected[f][target][12:15]))
            assert target_error<1e-4,target_error
            assert joint_error<1e-4,joint_error
            return dict(target_error=target_error,solver_joint_error=joint_error)
        report=errors()
        # Independently check that the new point graph follows an input edit
        # through native undo/redo, without editing any original scene nodes.
        c.currentTime(0);hips=rig['parts']['body']['controls']['hips']
        joints=[rig['parts']['leg_'+s]['joints'][0] for s in ('L','R')]
        original=[c.xform(j,q=True,ws=True,t=True) for j in joints]
        c.undoInfo(openChunk=True,chunkName='PointPrecisionMove')
        try:
            v=c.getAttr(hips+'.translateX')+.25
            if animated:c.setKeyframe(hips,at='translateX',t=0,v=v)
            else:c.setAttr(hips+'.translateX',v)
            c.dgdirty(hips)
        finally:c.undoInfo(closeChunk=True)
        moved=[c.xform(j,q=True,ws=True,t=True) for j in joints]
        assert all(abs(b[0]-a[0]-.25)<1e-8 for a,b in zip(original,moved)),(original,moved)
        c.undo()
        assert all(math.dist(a,c.xform(j,q=True,ws=True,t=True))<1e-8 for a,j in zip(original,joints))
        c.redo()
        assert all(math.dist(a,c.xform(j,q=True,ws=True,t=True))<1e-8 for a,j in zip(moved,joints))
        return dict(passed=True,animated=animated,frames=len(frames),undo_redo=True,**report)
    finally:
        if rig:suite['remove'](rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(time);c.autoKeyframe(state=auto)
        c.select(sel,r=True) if sel else c.select(clear=True)
        c.file(modified=modified)
        assert set(c.ls(long=True))==before
