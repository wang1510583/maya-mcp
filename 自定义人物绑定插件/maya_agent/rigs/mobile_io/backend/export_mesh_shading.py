"""Read-only mesh smoothing topology and Maya normals used to validate offline shading."""
import maya.cmds as c
import maya.api.OpenMaya as om

def mesh_metadata(mesh):
 node=c.ls(mesh['id'],long=True)[0];sel=om.MSelectionList();sel.add(node);fn=om.MFnMesh(sel.getDagPath(0));counts,ids=fn.getNormalIds()
 if not all(v==3 for v in counts) or any(fn.isNormalLocked(i) for i in range(fn.numNormals)):return None
 if list(fn.getTriangles()[1])!=mesh['triangles']:raise ValueError('Mesh shading topology differs from snapshot')
 corners=[];offset=0
 for face in range(fn.numPolygons):
  vv=list(fn.getPolygonVertices(face))
  for vertex in mesh['triangles'][face*3:face*3+3]:corners.append(int(ids[offset+vv.index(vertex)]))
  offset+=3
 return {'vertexCount':fn.numVertices,'normalCount':fn.numNormals,'normalIds':corners,'worldMatrix':list(c.getAttr(node+'.worldMatrix[0]')),'weighting':'face-area-times-corner-angle','hardEdges':sum(not fn.isEdgeSmooth(i) for i in range(fn.numEdges))}
