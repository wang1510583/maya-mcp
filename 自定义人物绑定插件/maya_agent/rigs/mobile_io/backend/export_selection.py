"""Explicit additions to one registered character; never gather the whole scene."""
import json
import maya.cmds as c
import maya.api.OpenMaya as om


def resolve(root, selection):
    root=c.ls(root,long=True)[0]
    meta=json.loads(c.getAttr(root+'.integratedRigData'))
    members={root}
    for part in meta['parts'].values():
        members.update(c.ls(part.get('root',''),long=True) or [])
        for key in ('controls','zero_controls'):
            for value in part.get(key,{}).values():members.update(c.ls(value,long=True) or [])
    if meta.get('master_control'):members.update(c.ls(meta['master_control'],long=True) or [])
    for item in meta.get('generic_objects',[]):members.update(c.ls(item['control_uuid'],long=True) or [])
    nodes=[]
    for item in selection:
        if '.' in item:raise ValueError('请使用物体选择模式，选择需要追加导出的完整物体，不支持组件选择。')
        found=c.ls(item,long=True) or []
        if len(found)!=1:raise ValueError('导出选择无效或名称不唯一：'+item)
        nodes.append(found[0])
    def belongs(n):return n in members or (c.nodeType(n)=='nurbsCurve' and any(n.startswith(m+'|') for m in members))
    # The UI's current character supplies the required rig and skins. Selection
    # only adds objects; it never gates or replaces that baseline.
    meshes=set();joints=set();cameras=set()
    for n in nodes:
        if belongs(n):continue
        descendants=[n]+(c.listRelatives(n,ad=True,fullPath=True) or [])
        if any(c.objExists(d+'.integratedRigData') and d!=root for d in descendants):raise ValueError('一次只能导出一套集成绑定。')
        found=False
        for d in descendants:
            typ=c.nodeType(d)
            if typ=='joint':joints.add(d);found=True
            elif typ in ('mesh','camera') and not c.getAttr(d+'.intermediateObject'):
                (meshes if typ=='mesh' else cameras).add(d);found=True
        if not found:raise ValueError('额外选择不包含骨骼、模型或相机：'+n)
    return dict(meshes=sorted(meshes),joints=sorted(joints),cameras=sorted(cameras),selection=nodes)


def append_rigid(meshes, joints, selected):
    existing={m['name'] for m in meshes}
    identity=list(om.MMatrix())
    for shape in selected:
        if shape in existing:continue
        if c.listConnections(shape+'.inMesh',s=True,d=False,type='geometryFilter'):
            raise ValueError('额外模型包含未支持的变形器：'+shape)
        history=c.listHistory(shape) or []
        if any(c.objectType(n,isAType='geometryFilter') for n in history):raise ValueError('额外模型包含未支持的变形器：'+shape)
        sel=om.MSelectionList();sel.add(shape);dp=sel.getDagPath(0);fn=om.MFnMesh(dp)
        parent=c.listRelatives(shape,p=True,fullPath=True)[0];uid=c.ls(parent,uuid=True)[0]
        joints.add(parent)
        meshes.append(dict(id=c.ls(shape,uuid=True)[0],name=shape,
            positions=[[p.x,p.y,p.z] for p in fn.getPoints(om.MSpace.kWorld)],triangles=list(fn.getTriangles()[1]),
            rigidTransform=parent,skin=dict(id=uid,name=parent,method=0,
                influences=[dict(id=uid,path=parent,bindPreMatrix=identity)],weights=[[0,1.] for _ in range(fn.numVertices)]),
            vertexSpace='evaluated_world_at_snapshot_frame'))
