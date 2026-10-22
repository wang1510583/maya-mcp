"""Bounded camera samples with Maya render-gate optics and restored scene time."""
import math, runpy
from pathlib import Path
from functools import lru_cache
import maya.cmds as c
import maya.api.OpenMaya as om


@lru_cache(maxsize=1)
def camera_io():
    return runpy.run_path(str(Path(__file__).with_name("camera_animation.py")))


def state(shape, aspect):
    sel=om.MSelectionList();sel.add(shape);dag=sel.getDagPath(0);fn=om.MFnCamera(dag)
    world=dag.inclusiveMatrix();tm=om.MTransformationMatrix(world);q=tm.rotation(asQuaternion=True)
    # Camera scale is not a lens or a view transform.
    rigid=q.asMatrix();rigid=list(rigid);rigid[12:15]=list(world)[12:15]
    near=float(fn.nearClippingPlane);far=float(fn.farClippingPlane)
    bounds=list(fn.getRenderingFrustum(aspect))
    if not (0<near<far) or not all(math.isfinite(v) for v in bounds+rigid):raise ValueError('无效的相机裁剪范围：'+shape)
    if c.getAttr(shape+'.panZoomEnabled'):raise ValueError('请先关闭相机的 2D Pan/Zoom 后导出：'+shape)
    return dict(world=rigid,frustum=bounds,near=near,far=far,ortho=bool(fn.isOrtho()),
                post=list(fn.postProjectionMatrix()),focus=max(near*2,float(fn.centerOfInterest)),lens=camera_io()["lens"](shape))


def key_frames(shape, start, end):
    # Include inherited transform animation and animated optics. Samples remain authoritative.
    nodes=[];node=shape
    while node:
        nodes.append(node);parents=c.listRelatives(node,parent=True,fullPath=True) or [];node=parents[0] if parents else None
    return sorted({float(t) for node in nodes for t in (c.keyframe(node,q=True,timeChange=True) or []) if start<=t<=end})


def capture(shapes,start,end):
    if not shapes:return []
    if c.currentUnit(q=True,angle=True)!='deg':raise ValueError('相机曲线导出要求角度单位为度')
    if len(shapes)>16 or (end-start+1)*len(shapes)>32000:raise ValueError('相机采样过多，请缩短范围或减少相机（最多 16 台、共 32000 帧）。')
    aspect=float(c.getAttr('defaultResolution.deviceAspectRatio'))
    if not .1<=aspect<=10:raise ValueError('无效的 Maya 渲染画幅比例。')
    before=c.currentTime(q=True);modified=c.file(q=True,modified=True)
    result=[dict(id=c.ls(s,uuid=True)[0],name=s.split('|')[-1],path=s,aspect=aspect,start=start,keyFrames=key_frames(s,start,end),sourceCurves=camera_io()["capture"](s),samples=[]) for s in shapes]
    try:
        for frame in range(start,end+1):
            c.currentTime(frame,edit=True)
            for shape,row in zip(shapes,result):row['samples'].append(state(shape,aspect))
    finally:
        c.currentTime(before,edit=True);c.dgdirty(allPlugs=True);c.refresh(force=True);c.file(modified=modified)
    for row in result:
        if all(s==row['samples'][0] for s in row['samples']):row['samples']=row['samples'][:1]
        elif not row['keyFrames']:row['samplingOnly']=True
    return result
