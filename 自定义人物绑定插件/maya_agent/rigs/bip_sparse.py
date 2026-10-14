"""Fit editable Maya curves without introducing new source key times."""
import math

GROUP_NAMES={'body':'身体','head':'头部','arm_L':'左手','arm_R':'右手','leg_L':'左脚','leg_R':'右脚'}


def group_for_part(part):
    return 'arm_'+part[-1] if part.startswith('shoulder_') else part


def group_schedules(data,target_fps,target_start,parts):
    """Six independent source schedules; root keys belong only to the body."""
    tracks=(data.get('source_keys') or {}).get('tracks')
    if tracks is None:raise ValueError('缺少分部位源关键帧信息，请重新从 Max 读取。')
    labels={'body':['Pelvis','Spine','Spine1','Spine2','COM Vertical','COM Horizontal','COM Turn'],
            'head':['Neck','Head']}
    for side in ('L','R'):
        labels['arm_'+side]=[side+' '+n for n in ('Clavicle','UpperArm','Forearm','Hand')]
        labels['leg_'+side]=[side+' '+n for n in ('Thigh','Calf','Foot','Toe0')]
    first=data['samples'][0]['frame'];last=data['samples'][-1]['frame'];out={}
    for group in sorted({group_for_part(p) for p in parts}):
        if group not in labels:raise ValueError('未知关键帧分组：'+group)
        keys=[]
        for label in labels[group]:
            name=data['root']+' '+label
            if name not in tracks:raise ValueError('缺少部位关键帧轨道：'+name)
            keys.extend(tracks[name])
        if any(not math.isfinite(float(f)) for f in keys):raise ValueError('源关键帧时间无效。')
        if not any(first-1e-8<=f<=last+1e-8 for f in keys):out[group]=[];continue
        subset=dict(data,source_keys={'times':keys})
        out[group]=key_schedule(subset,target_fps,target_start)
    return out


def plug_groups(baker):
    from .bip_retarget import _actual_plug
    out={}
    for p in baker.plugs:
        plug=_actual_plug(p);node=plug.split('.',1)[0].rsplit('|',1)[-1]
        groups={group_for_part(k) for k,part in baker.parts.items() if node.startswith(part['namespace']+':')}
        if len(groups)!=1:raise ValueError('无法确定动画通道所属部位：'+plug)
        out[plug]=groups.pop()
    return out


def key_schedule(data,target_fps,target_start):
    metadata=data.get('source_keys')
    if not metadata:
        raise ValueError('数据没有 BIP 原始关键帧时间，请重新从 Max 读取，或使用采样模式。')
    keys=metadata.get('times',[])
    if any(not math.isfinite(float(f)) for f in keys):raise ValueError('源关键帧时间无效。')
    first=data['samples'][0]['frame'];last=data['samples'][-1]['frame']
    keys=sorted({float(f) for f in keys if first-1e-8<=float(f)<=last+1e-8})
    if not keys:raise ValueError('所选范围没有源关键帧，请扩大范围，或使用采样模式。')
    sampled={round(float(s['frame']),8) for s in data['samples']}
    if any(round(f,8) not in sampled for f in keys):
        raise ValueError('采样数据缺少原始关键帧姿态，请重新从 Max 读取。')
    return [target_start+(f-first)*target_fps/data['fps'] for f in keys]


def fit_slopes(points,start,end,y0,y1):
    """Least-squares Hermite slopes with endpoints fixed, in value/frame."""
    span=end-start
    aa=ab=bb=ay=by=0.0
    for x,y in points:
        if not start<x<end:continue
        u=(x-start)/span
        a=u**3-2*u*u+u;b=u**3-u*u
        residual=y-((2*u**3-3*u*u+1)*y0+(-2*u**3+3*u*u)*y1)
        aa+=a*a;ab+=a*b;bb+=b*b;ay+=a*residual;by+=b*residual
    # An empty/underdetermined segment tends to the straight secant, not an
    # arbitrary overshooting tangent. Regularization only stabilizes rank loss.
    ridge=1e-9;delta=y1-y0
    aa+=ridge;bb+=ridge;ay+=ridge*delta;by+=ridge*delta
    determinant=aa*bb-ab*ab
    if determinant<1e-20:return delta/span,delta/span
    return (ay*bb-by*ab)/determinant/span,(by*aa-ay*ab)/determinant/span


def apply(baker,samples,schedules):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    from .bip_retarget import _actual_plug
    fps=om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
    values={round(t,8):row for t,row in samples}
    plugs=sorted({_actual_plug(p) for p in baker.plugs})
    owners=plug_groups(baker)
    modes={_actual_plug(p) for p in baker.mode_plugs}
    for plug in plugs:
        key_times=schedules[owners[plug]]
        c.cutKey(plug,time=(samples[0][0],samples[-1][0]),clear=True)
        if not key_times:
            if c.keyframe(plug,q=True,kc=True):
                raise ValueError('该部位没有源关键帧但保留范围外旧动画，请扩大导入范围：'+plug)
            incoming=c.connectionInfo(plug,sfd=True)
            if incoming:c.disconnectAttr(incoming,plug)
            c.setAttr(plug,values[round(samples[0][0],8)][plug])
            continue
        for t in key_times:
            c.setKeyframe(plug,t=t,v=values[round(t,8)][plug],
                          itt='linear',ott='step' if plug in modes else 'linear')
        if key_times[-1] < samples[-1][0]-1e-8:
            # A group's final source key holds through the rest of this clip.
            # An older key beyond the replaced interval must not pull that
            # hold toward the previous animation. No new boundary key is added.
            c.keyTangent(plug,time=(key_times[-1],key_times[-1]),lock=False,ott='step')
        if plug in modes or len(key_times)<2:continue
        curves=c.keyframe(plug,q=True,name=True) or []
        if not curves:
            # Some locked display-only TR plugs report settable through their
            # proxy but Maya deliberately creates no animCurve for them.
            if c.getAttr(plug,lock=True):continue
            raise RuntimeError('没有生成动画曲线：'+plug)
        if len(curves)!=1:raise RuntimeError('控制器动画曲线不唯一：'+plug)
        source=curves[0]
        selection=om.MSelectionList();selection.add(source)
        curve=oma.MFnAnimCurve(selection.getDependNode(0))
        factor=math.pi/180 if curve.animCurveType==oma.MFnAnimCurve.kAnimCurveTA else 1.0
        series=[(t,row[plug]) for t,row in samples]
        for left,right in zip(key_times,key_times[1:]):
            y0=values[round(left,8)][plug];y1=values[round(right,8)][plug]
            out_slope,in_slope=fit_slopes(series,left,right,y0,y1)
            for t,is_in,slope in ((left,False,out_slope),(right,True,in_slope)):
                options={'itt':'fixed'} if is_in else {'ott':'fixed'}
                if curve.isWeighted:options['weightLock']=False
                # Internal tangent units: seconds and cm / radians / unitless.
                options.update({'ix' if is_in else 'ox':(right-left)/fps/3,
                                'iy' if is_in else 'oy':slope*(right-left)*factor/3})
                c.keyTangent(plug,time=(t,t),lock=False,**options)
    c.dgdirty(list({p.split('.')[0] for p in plugs}))
    for plug in plugs:
        expected=schedules[owners[plug]]
        actual_times=c.keyframe(plug,q=True,tc=True,time=(samples[0][0],samples[-1][0])) or []
        if sorted({round(f,8) for f in actual_times})!=sorted({round(f,8) for f in expected}):
            raise RuntimeError('通道关键帧不符合部位时间：'+plug)
        for frame in expected:
            keyed=c.keyframe(plug,q=True,vc=True,time=(frame,frame)) or []
            wanted=values[round(frame,8)][plug]
            if len(keyed)!=1 or abs(keyed[0]-wanted)>1e-6:
                raise RuntimeError('源关键帧通道值校验失败：'+plug)
    actual={group:sorted({round(f,8) for p in plugs if owners[p]==group
                         for f in (c.keyframe(p,q=True,tc=True,time=(samples[0][0],samples[-1][0])) or [])})
            for group in schedules}
    for group,times in actual.items():
        if times!=sorted({round(f,8) for f in schedules[group]}):
            raise RuntimeError('部位源关键帧时间校验失败：'+group)
    return actual
