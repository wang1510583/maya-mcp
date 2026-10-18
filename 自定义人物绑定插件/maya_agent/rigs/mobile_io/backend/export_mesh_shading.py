"""Read-only mesh smoothing topology and Maya normals used to validate offline shading."""
import maya.cmds as c
import maya.api.OpenMaya as om

def mesh_metadata(mesh):
 node=c.ls(mesh['id'],long=True)[0];sel=om.MSelectionList();sel.add(node);fn=om.MFnMesh(sel.getDagPath(0));counts,ids=fn.getNormalIds()
 if any(fn.isNormalLocked(i) for i in range(fn.numNormals)):return None
 tri_counts,triangles=fn.getTriangles()
 if list(triangles)!=mesh['triangles']:raise ValueError('Mesh shading topology differs from snapshot')
 corners=[];polygon_vertices=[];offset=0;triangle_offset=0
 for face in range(fn.numPolygons):
  vv=list(fn.getPolygonVertices(face));local={vertex:int(ids[offset+j]) for j,vertex in enumerate(vv)}
  end=triangle_offset+int(tri_counts[face])*3
  corners.extend(local[int(vertex)] for vertex in triangles[triangle_offset:end])
  polygon_vertices.extend(vv);offset+=len(vv);triangle_offset=end
 data={'vertexCount':fn.numVertices,'normalCount':fn.numNormals,'normalIds':corners,'worldMatrix':list(c.getAttr(node+'.worldMatrix[0]')),'weighting':'face-area-times-corner-angle','hardEdges':sum(not fn.isEdgeSmooth(i) for i in range(fn.numEdges))}
 if any(v!=3 for v in counts):
  data.update(polygonCounts=list(counts),polygonVertices=polygon_vertices,polygonNormalIds=list(ids))
 return data
