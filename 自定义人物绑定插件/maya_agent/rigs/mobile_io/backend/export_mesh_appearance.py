"""Read-only static base-color export. Images are embedded PNGs, never source files."""
import base64, hashlib, math, os
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om
from PySide2.QtCore import QByteArray, QBuffer, QIODevice
from PySide2.QtGui import QImage

MAX_SIZE = 1024
MAX_PIXELS = 4 * 1024 * 1024

def appearance(snapshot, sha):
    images, meshes, warnings = {}, {}, []
    def material(sg):
        sources = c.listConnections(sg + '.surfaceShader', s=True, d=False) or []
        row = {'color': [.69, .77, .84]}
        if not sources:
            return row
        node = sources[0]; kind = c.nodeType(node)
        attr = 'baseColor' if kind == 'aiStandardSurface' else 'color'
        if kind not in ('lambert', 'phong', 'blinn', 'surfaceShader', 'aiStandardSurface'):
            warnings.append('Unsupported base-color shader: ' + node); return row
        plug = node + '.' + attr
        source = c.listConnections(plug, s=True, d=False, p=True) or []
        if not source:
            row['color'] = list(c.getAttr(plug)[0]); return row
        tex = source[0].split('.')[0]
        if c.nodeType(tex) != 'file' or source[0].split('.')[-1] != 'outColor':
            warnings.append('Unsupported base-color network: ' + plug); return row
        if c.getAttr(tex + '.useFrameExtension') or c.getAttr(tex + '.uvTilingMode'):
            warnings.append('Animated/UDIM texture omitted: ' + tex); return row
        if any(c.listConnections(tex+'.'+a,s=True,d=False) for a in ('colorGain','colorOffset','invert')) or c.getAttr(tex+'.colorGain')[0] != (1.,1.,1.) or c.getAttr(tex+'.colorOffset')[0] != (0.,0.,0.) or c.getAttr(tex+'.invert'):
            warnings.append('Texture color adjustment omitted: '+tex);return row
        if c.listConnections(tex + '.uvCoord', s=True, d=False, type='place2dTexture'):
            placement = c.listConnections(tex + '.uvCoord', s=True, d=False, type='place2dTexture')[0]
            for attr, expected in [('coverage', (1.,1.)), ('translateFrame',(0.,0.)), ('rotateFrame',0.), ('rotateUV',0.), ('offset',(0.,0.)), ('repeatUV',(1.,1.)), ('mirrorU',False), ('mirrorV',False), ('stagger',False)]:
                value=c.getAttr(placement+'.'+attr)
                if isinstance(value,list):value=value[0]
                if value != expected or c.listConnections(placement+'.'+attr,s=True,d=False):
                    warnings.append('Non-default UV placement omitted: '+tex);return row
        # A direct file outColor is a complete base color; its shader.color evaluates
        # at an arbitrary UV and must not be multiplied into the image.
        path = os.path.expandvars(c.getAttr(tex + '.fileTextureName'))
        if not os.path.isabs(path): path = c.workspace(expandName=path)
        image = QImage(path)
        if image.isNull():
            warnings.append('Unreadable texture: ' + path); return row
        if max(image.width(), image.height()) > MAX_SIZE:
            from PySide2.QtCore import Qt
            image=image.scaled(MAX_SIZE, MAX_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # ES2 repeat+mipmaps require power-of-two dimensions. Bound the result.
        w=1 << max(0, int(math.ceil(math.log(max(1,image.width()),2))))
        h=1 << max(0, int(math.ceil(math.log(max(1,image.height()),2))))
        if (w,h)!=(image.width(),image.height()):image=image.scaled(w,h)
        image=image.convertToFormat(QImage.Format_RGB888) # base color only, opaque
        data=QByteArray(); buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer,'PNG'):raise ValueError('PNG encoding failed: '+path)
        raw=bytes(data);key=hashlib.sha256(raw).hexdigest()
        if key not in images:
            if sum(i['width']*i['height'] for i in images.values())+w*h>MAX_PIXELS:
                warnings.append('Texture pixel budget exceeded: '+path);return row
            images[key]={'width':w,'height':h,'mime':'image/png','data':base64.b64encode(raw).decode('ascii')}
        row.update(color=[1.,1.,1.],texture=key)
        return row
    for mesh in snapshot['meshes']:
        node=c.ls(mesh['id'],long=True)[0];selection=om.MSelectionList();selection.add(node)
        dag=selection.getDagPath(0);fn=om.MFnMesh(dag);counts,triangles=fn.getTriangles()
        if list(triangles)!=mesh['triangles']:raise ValueError('Texture topology differs from snapshot')
        shaders, assignments=fn.getConnectedShaders(dag.instanceNumber())
        materials=[material(om.MFnDependencyNode(s).name()) for s in shaders] or [{'color':[.69,.77,.84]}]
        face_materials=[];uv_ids=[];uvs=[]
        try:
            uvset=fn.currentUVSetName();u,v=fn.getUVs(uvset)
            uvs=[[float(a),float(b)] for a,b in zip(u,v)]
            triangle_offset=0
            for face,count in enumerate(counts):
                vertices=list(fn.getPolygonVertices(face));local={vertex:fn.getPolygonUVid(face,j,uvset) for j,vertex in enumerate(vertices)}
                end=triangle_offset+int(count)*3
                uv_ids.extend(local[int(vertex)] for vertex in triangles[triangle_offset:end]);triangle_offset=end
        except RuntimeError:
            warnings.append('Missing/incomplete UVs: '+node)
            uvs=[[0.,0.]];uv_ids=[0]*len(triangles)
            for row in materials:row.pop('texture',None)
        for face,count in enumerate(counts):face_materials.extend([max(0,int(assignments[face])) if assignments else 0]*int(count))
        meshes[mesh['id']]={'uvs':uvs,'uvIds':uv_ids,'materials':materials,'triangleMaterials':face_materials}
    return {'format':'maya-mesh-appearance','version':1,'sourceSnapshotSha256':sha,'meshes':meshes,'images':images,'warnings':warnings}
