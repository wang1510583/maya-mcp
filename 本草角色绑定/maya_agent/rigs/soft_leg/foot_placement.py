"""Read a skinned foot's bind sole and transport it with the ankle, without editing skin."""
import math


def from_targets(ankle,toe):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    ankle=(c.ls(ankle,long=True) or [ankle])[0]
    toe=(c.ls(toe,long=True) or [toe])[0]
    candidates=c.listConnections(ankle+'.worldMatrix[0]',s=False,d=True,type='skinCluster') or []
    for skin in sorted(set(candidates)):
        selection=om.MSelectionList();selection.add(skin)
        fn=oma.MFnSkinCluster(selection.getDependNode(0))
        influences=fn.influenceObjects();names=[p.fullPathName() for p in influences]
        if ankle not in names or toe not in names:continue
        physical=[names.index(ankle),names.index(toe)]
        logical=[fn.indexForInfluenceObject(influences[i]) for i in physical]
        bind=[om.MMatrix(c.getAttr(skin+'.bindPreMatrix[{}]'.format(i))).inverse() for i in logical]
        a=list(bind[0])[12:15];t=list(bind[1])[12:15]
        forward=om.MVector(t[0]-a[0],0,t[2]-a[2])
        if forward.length()<1e-6:continue
        forward.normalize()
        geometry_matrix=om.MMatrix(c.getAttr(skin+'.geomMatrix'))
        points=[]
        for index in c.getAttr(skin+'.input',multiIndices=True) or []:
            path=fn.getPathAtIndex(index)
            if not path.node().hasFn(om.MFn.kMesh):continue
            plug=om.MFnDependencyNode(fn.object()).findPlug('input',False).elementByLogicalIndex(index).child(0)
            mesh=om.MFnMesh(plug.asMObject());rest=mesh.getPoints(om.MSpace.kObject)
            components=om.MFnSingleIndexedComponent();component=components.create(om.MFn.kMeshVertComponent)
            components.setCompleteData(len(rest))
            weights=fn.getWeights(path,component,om.MIntArray(physical))
            points.extend(p*geometry_matrix for i,p in enumerate(rest) if sum(weights[i*2:i*2+2])>.2)
        if len(points)<4:continue
        floor=min(p.y for p in points)
        # Use the sole region rather than the ankle/calf silhouette for heel/toe ends.
        band=max(math.dist(a,t)*.1,1e-4)
        sole=[p for p in points if p.y<=floor+band]
        distances=[(om.MVector(p.x-a[0],0,p.z-a[2])*forward) for p in sole]
        if len(distances)<3 or max(distances)-min(distances)<1e-5:continue
        rest_points={
            'heel':[a[0]+forward.x*min(distances),floor,a[2]+forward.z*min(distances)],
            'toe_end':[a[0]+forward.x*max(distances),floor,a[2]+forward.z*max(distances)],
            'toe':[t[0],floor,t[2]],
        }
        delta=bind[0].inverse()*om.MMatrix(c.xform(ankle,q=True,ws=True,m=True))
        up=om.MVector(0,1,0);right=up^forward
        basis=om.MMatrix([right.x,right.y,right.z,0,-forward.x,-forward.y,-forward.z,0,
                         up.x,up.y,up.z,0,0,0,0,1])
        rotation=om.MTransformationMatrix(basis*delta).rotation(asQuaternion=True).asEulerRotation()
        return dict(method='skin_bind_sole',skin=skin,ankle=ankle,toe=toe,
                    bind_ankle=list(bind[0]),bind_points=rest_points,
                    rotation=[math.degrees(v) for v in rotation],
                    points={k:list(om.MPoint(p)*delta)[:3] for k,p in rest_points.items()})
    return None
