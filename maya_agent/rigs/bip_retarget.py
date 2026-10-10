"""Biped retargeting with source ankle trajectories and native controller bake."""
import json
import math
from pathlib import Path

TR = tuple(p+a for p in ('translate','rotate') for a in 'XYZ')
ROLE_NAMES = {'body':['Pelvis','Spine','Spine1','Spine2'], 'head':['Neck','Head']}
for _side in ('L','R'):
    ROLE_NAMES['shoulder_'+_side]=[_side+' Clavicle']
    ROLE_NAMES['arm_'+_side]=[_side+' UpperArm',_side+' Forearm',_side+' Hand']
    ROLE_NAMES['leg_'+_side]=[_side+' Thigh',_side+' Calf',_side+' Foot',_side+' Toe0']


def read_data(data):
    if isinstance(data,(str,Path)):
        data=json.loads(Path(data).read_text(encoding='utf-8'))
    if not data.get('reference'):
        raise ValueError('缺少 Max Figure Mode 参考姿态，请重新从 Max 采集。')
    if not data.get('samples') or len(data['samples'])>10001:
        raise ValueError('采样数量必须为 1–10001。')
    if data.get('up_axis')!='Z' or not math.isfinite(float(data.get('fps',0))) or float(data.get('fps',0))<=0:
        raise ValueError('需要包含帧率和 Z-up 信息的 Max 采样。')
    last=-float('inf')
    for sample in data['samples']:
        f=float(sample['frame'])
        if not math.isfinite(f) or f<=last:raise ValueError('采样帧必须有限且严格递增。')
        last=f
    return data


def com_source(data):
    """Never infer COM from Pelvis: they share a pivot, not a rotation."""
    name=data.get('root')
    if not name or name not in data['reference'] or any(name not in s['bones'] for s in data['samples']):
        raise ValueError('旧数据未采集 Bip001 总根运动，请重新从 BIP 文件或 Max 采集后导入。')
    return name


def _matrix(value):
    import maya.api.OpenMaya as om
    if len(value)==4:
        value=[v for row in value[:3] for v in list(row)+[0.0]]+list(value[3])+[1.0]
    if len(value)!=16 or not all(math.isfinite(float(x)) for x in value):
        raise ValueError('BIP 矩阵无效。')
    return om.MMatrix(value)


def _pos(m):
    import maya.api.OpenMaya as om
    return om.MVector(*list(m)[12:15])


def _rot(m):
    import maya.api.OpenMaya as om
    return om.MTransformationMatrix(m).rotation(asQuaternion=True).asMatrix()


def _pose(rotation,position):
    import maya.api.OpenMaya as om
    values=list(rotation);values[12:15]=list(position)
    return om.MMatrix(values)


def _knee_position(hip, ankle, hint, upper, lower):
    """Two-bone IK with fixed lengths and a source-space bend hint."""
    import maya.api.OpenMaya as om
    axis=ankle-hip;distance=axis.length()
    if distance<1e-6 or distance>upper+lower+1e-4 or distance<abs(upper-lower)-1e-4:
        raise ValueError('BIP 脚步超出当前腿长可达范围，需要调整角色比例或根运动。')
    axis/=distance
    bend=hint-hip-axis*((hint-hip)*axis)
    if bend.length()<1e-6:
        raise ValueError('BIP 腿部完全伸直，无法确定膝盖方向。')
    along=(upper*upper-lower*lower+distance*distance)/(2*distance)
    return hip+axis*along+bend.normal()*math.sqrt(max(0,upper*upper-along*along))


def _rig(root):
    import maya.cmds as c
    if root is None:
        roots=[n for n in (c.ls(type='transform',long=True) or [])
               if c.objExists(n+'.integratedRigData')]
        if len(roots)!=1:raise ValueError('请明确选择一套集成角色绑定。')
        root=roots[0]
    return json.loads(c.getAttr(root+'.integratedRigData'))


def _actual_plug(plug):
    """Follow Maya proxy attributes, without traversing arbitrary DG drivers."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    visited=set()
    while plug not in visited:
        visited.add(plug)
        selection=om.MSelectionList();selection.add(plug)
        attribute=selection.getPlug(0).attribute()
        # addAttr -q -proxy also returns a name on the ordinary backing
        # attribute. Only the API flag distinguishes a real proxy; otherwise
        # this walk incorrectly continues into the animation curve's output.
        if not om.MFnAttribute(attribute).isProxyAttribute:break
        src=c.connectionInfo(plug,sfd=True)
        if not src:break
        plug=src
    return plug


def _targets(rig):
    return {k:[row['target'] for row in p['original_target_mapping']] for k,p in rig['parts'].items()}


def target_profile(root=None,reference_frame=None):
    """Capture the saved Maya bind proportions, never the current animated pose."""
    import maya.cmds as c
    from max_mcp.biped_retarget import validate_profile
    rig=_rig(root);targets=_targets(rig)
    if c.currentUnit(q=True,linear=True)!='cm' or c.upAxis(q=True,axis=True)!='y':
        raise ValueError('Biped 原生适配要求 Maya 使用厘米和 Y-up。')
    old=c.currentTime(q=True)
    if c.objExists(rig['root']+'.bipRetargetCalibration'):
        rest=json.loads(c.getAttr(rig['root']+'.bipRetargetCalibration'))['rest']
    else:
        try:
            if reference_frame is not None:c.currentTime(reference_frame)
            rest={n:c.xform(n,q=True,ws=True,m=True) for nodes in targets.values() for n in nodes}
        finally:c.currentTime(old)
    points={}
    for key,nodes in targets.items():
        if len(nodes)!=len(ROLE_NAMES.get(key,[])):raise ValueError('不支持的部位数量：'+key)
        for node,label in zip(nodes,ROLE_NAMES[key]):
            m=rest[node];points[label]=[m[12],-m[14],m[13]]
    profile=dict(version=1,points=points)
    try:validate_profile(profile)
    except ValueError as exc:
        raise ValueError('原生适配需要完整的腰+3节脊柱、颈头、双肩、双臂和双腿，且关节不能重合。'+str(exc)) from exc
    return profile


def plan(data, root=None, reference_frame=None, start_frame=None):
    """Read-only conversion plan. Calibrate against the current target rest pose."""
    import maya.cmds as c
    import maya.api.OpenMaya as om
    data=read_data(data);rig=_rig(root);targets=_targets(rig)
    native=data.get('native_retarget')
    if native:
        from max_mcp.biped_retarget import validate_profile, PAIRS
        points=validate_profile(native['profile']);current=target_profile(rig['root'],reference_frame)['points']
        pairs=PAIRS+[('L Thigh','R Thigh'),('L Clavicle','R Clavicle')]
        if max(abs(math.dist(points[a],points[b])-math.dist(current[a],current[b])) for a,b in pairs)>.002:
            raise ValueError('这份 Biped 适配数据属于其他身材，请按当前角色重新从 Max 导入。')
        if native.get('version',1)>=2:
            # The new fitting also depends on ankle height and shoulder socket
            # position; equal bone lengths alone no longer establish a match.
            origin=points['Pelvis'];current_origin=current['Pelvis']
            if any(math.dist([v-o for v,o in zip(p,origin)],
                             [v-o for v,o in zip(current[n],current_origin)])>.002
                   for n,p in points.items()):
                raise ValueError('这份 Biped 数据的参考姿态与当前角色不同，请重新读取 BIP。')
    if c.currentUnit(q=True,linear=True)!='cm' or c.currentUnit(q=True,angle=True)!='deg':
        raise ValueError('当前绑定导入要求 Maya 使用厘米和角度。')
    if len(targets.get('body',[]))!=4 or len(targets.get('head',[])) not in (0,2):
        raise ValueError('首版要求身体为腰+3节脊柱，头颈为颈+头。')
    old=c.currentTime(q=True);ref=old if reference_frame is None else reference_frame
    calibration=(json.loads(c.getAttr(rig['root']+'.bipRetargetCalibration'))
                 if c.objExists(rig['root']+'.bipRetargetCalibration') else None)
    if calibration:rest={n:_matrix(v) for n,v in calibration['rest'].items()}
    else:
        try:
            c.currentTime(ref)
            rest={n:_matrix(c.xform(n,q=True,ws=True,m=True)) for nodes in targets.values() for n in nodes}
        finally:c.currentTime(old)
    names={};src={};parents={}
    prefix=data['root']+' '
    for key,nodes in targets.items():
        if len(nodes)!=len(ROLE_NAMES.get(key,[])):raise ValueError('不支持的部位数量：'+key)
        for n,label in zip(nodes,ROLE_NAMES[key]):
            name=prefix+label
            if name not in data['reference']:raise ValueError('Max 缺少参考骨骼：'+name)
            if any(name not in s['bones'] for s in data['samples']):raise ValueError('Max 采样缺少骨骼：'+name)
            names[n]=name
    # Convert global coordinates before remapping each joint's local axes.
    coord=om.MMatrix([1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1])
    if c.upAxis(q=True,axis=True)!='y':raise ValueError('首版要求 Maya 为 Y-up。')
    src={n:_matrix(data['reference'][name])*coord for n,name in names.items()}
    for n in rest:
        par=(c.listRelatives(n,p=True,f=True) or [None])[0]
        parents[n]=par if par in rest else None
    # Match heading from the left/right hip direction; retain upright Y.
    left=targets.get('leg_L',[None])[0];right=targets.get('leg_R',[None])[0]
    if not left or not right:raise ValueError('自动比例需要两侧腿部。')
    sv=_pos(src[left])-_pos(src[right]);tv=_pos(rest[left])-_pos(rest[right])
    sv.y=tv.y=0
    heading=sv.rotateTo(tv).asMatrix()
    coord*=heading
    src={n:_matrix(data['reference'][name])*coord for n,name in names.items()}
    scale=sum(sum((_pos(rest[b])-_pos(rest[a])).length() for a,b in zip(targets[k][:2],targets[k][1:3])) for k in ('leg_L','leg_R'))/sum(sum((_pos(src[b])-_pos(src[a])).length() for a,b in zip(targets[k][:2],targets[k][1:3])) for k in ('leg_L','leg_R'))
    if native:scale=1.0
    rotation_offsets={}
    # Full anatomical frames resolve roll as well as aim. In particular the
    # ankle-to-ball slope is not the foot sole's pitch, and a shortest-arc
    # shoulder rotation cannot establish the arm's bend plane.
    from .bip_reference import frames as reference_frames
    target_axes=reference_frames({names[n][len(prefix):]:list(_pos(rest[n])) for n in names})
    source_axes=reference_frames({names[n][len(prefix):]:list(_pos(src[n])) for n in names})
    for n in sorted(rest,key=lambda x:x.count('|')):
        label=names[n][len(prefix):]
        q=_matrix(target_axes[label]).inverse()*_matrix(source_axes[label])
        rotation_offsets[n]=_rot(rest[n])*q*_rot(src[n]).inverse()
    pelvis=targets['body'][0]
    first=data['samples'][0]['frame'];start=first if start_frame is None else float(start_frame)
    if not math.isfinite(start):raise ValueError('Maya 动画起点必须为有限数值。')
    fps=om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit())
    result=[];com_frames={}
    com_name=com_source(data)
    com_ref=_matrix(data['reference'][com_name])*coord
    # Preserve the rig's neutral control axes while transporting the actual
    # Biped COM rotation. Pelvis anatomy is handled separately in the output.
    com_rotation_offset=_rot(com_ref).inverse()
    origin=_pos(rest[pelvis])-_pos(src[pelvis])*scale
    if native and native.get('center_start'):
        first_pelvis=_pos(_matrix(data['samples'][0]['bones'][names[pelvis]])*coord)
        origin.x=_pos(rest[pelvis]).x-first_pelvis.x
        origin.z=_pos(rest[pelvis]).z-first_pelvis.z
    for sample in data['samples']:
        frame=start+(sample['frame']-first)*fps/data['fps']
        com=_matrix(sample['bones'][com_name])*coord
        com_frames[frame]=_pose(com_rotation_offset*_rot(com),_pos(com)*scale+origin)
        source={n:_matrix(sample['bones'][name])*coord for n,name in names.items()}
        rotations={n:rotation_offsets[n]*_rot(source[n]) for n in names}
        if native:
            world={n:_pose(rotations[n],_pos(source[n])*scale+origin) for n in names}
            result.append((start+(sample['frame']-first)*fps/data['fps'],world))
            continue
        world={}
        for n in sorted(rest,key=lambda x:x.count('|')):
            p=parents[n]
            if p:
                local=(_pos(rest[n])-_pos(rest[p]))*_rot(rest[p]).inverse()
                pos=_pos(world[p])+local*rotations[p]
            else:
                pos=_pos(rest[n])+(_pos(source[n])-_pos(src[n]))*scale
            world[n]=_pose(rotations[n],pos)
        # Preserve the actual source ankle trajectories. Rebuilding an ankle
        # from target FK lengths moves planted feet when body proportions differ.
        for side in ('L','R'):
            hip,knee,ankle,toe=targets['leg_'+side]
            end=_pos(source[ankle])*scale+origin
            hint=_pos(source[knee])*scale+origin
            upper=(_pos(rest[knee])-_pos(rest[hip])).length()
            lower=(_pos(rest[ankle])-_pos(rest[knee])).length()
            middle=_knee_position(_pos(world[hip]),end,hint,upper,lower)
            old_hip,old_knee,old_ankle=[_pos(world[n]) for n in (hip,knee,ankle)]
            for n,a,b in ((hip,old_knee-old_hip,middle-old_hip),
                          (knee,old_ankle-old_knee,end-middle)):
                rotations[n]*=a.rotateTo(b).asMatrix()
            toe_delta=_pos(world[toe])-old_ankle
            world[hip]=_pose(rotations[hip],old_hip)
            world[knee]=_pose(rotations[knee],middle)
            world[ankle]=_pose(rotations[ankle],end)
            world[toe]=_pose(rotations[toe],end+toe_delta)
        result.append((start+(sample['frame']-first)*fps/data['fps'],world))
    return dict(rig=rig,targets=targets,rest=rest,frames=result,scale=scale,
                reference_frame=ref,source_fps=data['fps'],mapping=names,calibration=calibration,native=native,com_frames=com_frames)


class Baker:
    def __init__(self,job):
        import maya.cmds as c
        from . import zero_channels as z, live_edit as le
        self.c=c;self.z=z;self.le=le;self.job=job;self.parts=job['rig']['parts']
        self.dest={};self.plugs=set();self.offsets={};self.orientation=[]
        for k,p in self.parts.items():
            if c.objExists(p['root']+'.liveAlignmentData'):
                d=json.loads(c.getAttr(p['root']+'.liveAlignmentData'))
                self.dest.update({e['source']:e['proxy'] for e in d['entries']})
        for p in self.parts.values():
            for n in p.get('zero_controls',{}).values():
                for a in TR:
                    plug=n+'.'+a
                    if not c.getAttr(plug,lock=True):self.plugs.add(plug)
        self.rest_inputs={n:le._frame(n) for p in self.parts.values() for n in p['controls'].values()}
        for key,p in self.parts.items():
            targets=job['targets'][key]
            if key=='body':controls=[row['control'] for row in p['target_mapping']]
            elif key=='head':controls=[row['control'] for row in p['target_mapping']]
            elif key.startswith('shoulder'):controls=[p['controls']['clavicle']]
            elif key.startswith('arm'):controls=[p['controls'][r] for r in ('shoulder_fk','middle_fk','end_fk')]
            else:controls=[p['controls'][r] for r in ('hip','knee','foot','toe')]
            for n,t in zip(controls,targets):
                self.offsets[n]=job['rest'][t]*le._frame(n).inverse()
        if job['calibration']:
            self.offsets={n:_matrix(v) for n,v in job['calibration']['offsets'].items()}
        self.mode_plugs=[]
        for key,p in self.parts.items():
            if key=='body':
                from .body_direction import _data
                d=_data(p['controls']['hips']);modes=[d['global_plug'],d.get('chest_global')]
                modes=[self.z.surface(m.split('.')[0])+'.'+m.split('.')[1] for m in modes if m]
            else:modes=[n+'.global' for n in p.get('zero_controls',{}).values() if c.objExists(n+'.global')]
            self.mode_plugs.extend(modes);self.plugs.update(modes)
            for n in p.get('zero_controls',{}).values():
                for attr in ['bipRotate'+a for a in 'XYZ']+['bipPelvisRotate'+a for a in 'XYZ']+['positionOffset'+a for a in 'XYZ']+['bipHipTranslate'+a for a in 'XYZ']:
                    if c.objExists(n+'.'+attr):self.plugs.add(n+'.'+attr)

    def dst(self,node,attr):
        return self.z.resolve(self.dest.get(node+'.'+attr,node+'.'+attr))

    def world(self,n,m,translate=True):
        self.le._world(n,m,self.dest,solve_translation=translate)

    def position(self,n,p):
        self.world(n,_pose(_rot(self.le._frame(n)),p))

    def initialize(self):
        c=self.c
        for plug in self.mode_plugs:c.setAttr(plug,0)
        # Native Biped thigh sockets differ from this rig's fixed pelvis
        # attachments. Animate the genuine IK hip input through visible settings
        # channels, with no keys on bones and no downstream output correction.
        if self.job.get('native'):
            for key,p in self.parts.items():
                if not key.startswith('leg'):continue
                ctrl=p['zero_controls']['settings'];goal=p['hip_point_link']['driver']
                if c.objExists(ctrl+'.bipHipInput'):
                    adder=(c.listConnections(ctrl+'.bipHipInput',s=True,d=False) or [None])[0]
                    if not adder or c.connectionInfo(goal+'.translate',sfd=True)!=adder+'.output3D':
                        raise ValueError('BIP 髋输入连接已被修改：'+goal)
                else:
                    incoming=c.connectionInfo(goal+'.translate',sfd=True)
                    if not incoming:raise ValueError('BIP 髋起点缺少原生点跟随：'+goal)
                    adder=c.createNode('plusMinusAverage',name=p['namespace']+':bipHipInput')
                    c.connectAttr(incoming,adder+'.input3D[0]')
                    c.connectAttr(adder+'.output3D',goal+'.translate',force=True)
                    c.addAttr(ctrl,ln='bipHipInput',at='message');c.connectAttr(adder+'.message',ctrl+'.bipHipInput')
                for axis in 'XYZ':
                    src=ctrl+'.bipHipTranslate'+axis;dst=adder+'.input3D[1].input3D'+axis.lower()
                    if not c.objExists(src):
                        c.addAttr(ctrl,ln='bipHipTranslate'+axis,nn='BIP髋偏移'+axis,
                                  at='doubleLinear',defaultValue=0,keyable=True)
                        c.connectAttr(src,dst)
                    elif c.connectionInfo(dst,sfd=True)!=src:raise ValueError('BIP 髋输入连接已被修改：'+dst)
                    self.plugs.add(src)
        # Orientation residuals are explicit editable controller channels, like
        # the existing copy-animation feature; translations stay solver-only.
        for key,p in self.parts.items():
            if key!='body' and not key.startswith(('arm','leg')):continue
            roles=('hips',) if key=='body' else (('shoulder_fk','middle_fk','end_fk') if key.startswith('arm') else ('settings','knee','foot','toe'))
            channel='bipPelvisRotate' if key=='body' else 'bipRotate'
            for i,(row,t,role) in enumerate(zip(p['target_mapping'],self.job['targets'][key],roles)):
                joint=row['joint'];constraint=row['constraint']
                ctrl=p.get('zero_controls',{}).get(role) or self.z.surface(p['controls'][role])
                tag=('bipPelvisOrientation' if key=='body' else 'bipOrientation')+str(i+1)
                if c.objExists(ctrl+'.'+tag):
                    driver=(c.listConnections(ctrl+'.'+tag,s=True,d=False) or [None])[0]
                else:
                    driver=c.createNode('transform',name=p['namespace']+':'+tag,parent=joint,skipSelect=True)
                    c.addAttr(ctrl,ln=tag,at='message');c.connectAttr(driver+'.message',ctrl+'.'+tag)
                    pairs=c.listConnections(constraint,s=True,d=False,p=True,c=True) or []
                    for dst,src in zip(pairs[::2],pairs[1::2]):
                        if '.target[0].' not in dst or src.split('.')[0]!=joint:continue
                        a=src.split('.',1)[1]
                        c.disconnectAttr(src,dst)
                        if c.objExists(driver+'.'+a):c.connectAttr(driver+'.'+a,dst)
                        elif 'JointOrient' in dst:c.setAttr(dst,0,0,0)
                        elif 'InverseScale' in dst:c.setAttr(dst,1,1,1)
                        elif 'ScaleCompensate' in dst:c.setAttr(dst,False)
                    for axis in 'XYZ':
                        attr=channel+axis
                        if not c.objExists(ctrl+'.'+attr):c.addAttr(ctrl,ln=attr,nn=('BIP骨盆旋转' if key=='body' else 'BIP旋转')+axis,at='doubleAngle',keyable=True)
                        c.connectAttr(ctrl+'.'+attr,driver+'.rotate'+axis)
                # Existing constraint offsets and integrated outputs are static.
                if c.objExists(driver+'.bipBindOffset'):
                    offset=_matrix(c.getAttr(driver+'.bipBindOffset'))
                else:
                    offset=_matrix(c.xform(t,q=True,ws=True,m=True))*_matrix(c.xform(joint,q=True,ws=True,m=True)).inverse()
                    c.addAttr(driver,ln='bipBindOffset',dt='matrix')
                    c.setAttr(driver+'.bipBindOffset',*list(offset),type='matrix')
                self.orientation.append((driver,ctrl,t,offset,channel))
                for axis in 'XYZ':self.plugs.add(ctrl+'.'+channel+axis)
        root=self.job['rig']['root']
        if not self.job['calibration']:
            c.addAttr(root,ln='bipRetargetCalibration',dt='string')
            c.setAttr(root+'.bipRetargetCalibration',json.dumps(dict(
                rest={n:list(m) for n,m in self.job['rest'].items()},
                offsets={n:list(m) for n,m in self.offsets.items()})),type='string')

    def solve_body(self,world,com):
        from .body_direction import _linear_solve
        p=self.parts['body'];c=self.c
        controls=[r['control'] for r in p['target_mapping']];targets=self.job['targets']['body']
        desired={n:self.offsets[n].inverse()*world[t] for n,t in zip(controls,targets)}
        hips=controls[0]
        neutral=self.offsets[hips].inverse()*self.job['rest'][targets[0]]
        desired[hips]=_pose(_rot(neutral)*_rot(com),_pos(com))
        for n in [controls[0],controls[-1]]+controls[1:-1]:self.world(n,desired[n],False)
        plugs=[self.dst(n,'translate'+a) for n in controls for a in 'XYZ']
        def positions():return [v for t in targets for v in c.xform(t,q=True,ws=True,t=True)]
        base=positions();columns=[]
        for plug in plugs:
            v=c.getAttr(plug);c.setAttr(plug,v+1)
            columns.append([x-y for x,y in zip(positions(),base)]);c.setAttr(plug,v)
        desired=[v for t in targets for v in _pos(world[t])]
        for _ in range(3):
            residual=[a-b for a,b in zip(desired,positions())]
            if max(abs(v) for v in residual)<1e-6:break
            delta=_linear_solve(list(zip(*columns)),residual)
            for plug,v in zip(plugs,delta):c.setAttr(plug,c.getAttr(plug)+v)

    def solve(self,world,com):
        import maya.api.OpenMaya as om
        from .soft_limb.selection import _geometry
        c=self.c;self.solve_body(world,com)
        for key,p in self.parts.items():
            targets=self.job['targets'][key];ctrl=p['controls']
            if key.startswith('shoulder'):
                n=ctrl['clavicle'];self.world(n,self.offsets[n].inverse()*world[targets[0]])
        if 'head' in self.parts:
            p=self.parts['head'];ctrl=p['controls'];targets=self.job['targets']['head']
            n=ctrl['head'];self.world(n,self.offsets[n].inverse()*world[targets[-1]],False)
            for row,t in zip(p['target_mapping'][:-1],targets[:-1]):
                n=row['control'];self.world(n,self.offsets[n].inverse()*world[t])
            n=ctrl['head'];wanted=self.offsets[n].inverse()*world[targets[-1]]
            parent=_matrix(c.getAttr(n+'.parentMatrix[0]'))
            delta=(_pos(wanted)-_pos(self.le._frame(n)))*parent.inverse()
            visible=p.get('zero_controls',{}).get('head',n)
            for a,v in zip('XYZ',delta):
                plug=visible+'.positionOffset'+a
                c.setAttr(plug,c.getAttr(plug)+v);self.plugs.add(plug)
        for key,p in self.parts.items():
            if not key.startswith(('arm','leg')):continue
            ctrl=p['controls'];targets=self.job['targets'][key];points=[_pos(world[t]) for t in targets]
            samples=[dict(position=list(v),matrix=list(world[t])) for v,t in zip(points,targets)]
            frames,pole,_=_geometry(samples[:3])
            if key.startswith('arm'):
                for role,m in zip(('shoulder_fk','middle_fk','end_fk'),frames):self.world(ctrl[role],_matrix(m))
                hand=ctrl['end_locator']
                for a in TR:
                    plug=self.dst(hand,a)
                    if not c.getAttr(plug,lock=True):c.setAttr(plug,-self.z.offset(plug))
                self.position(ctrl['pole_locator'],om.MVector(pole))
            else:
                if self.job.get('native'):
                    hip=ctrl['hip']
                    delta=points[0]-_pos(_matrix(c.xform(hip,q=True,ws=True,m=True)))
                    for a,v in zip('XYZ',delta):
                        plug=p['zero_controls']['settings']+'.bipHipTranslate'+a
                        c.setAttr(plug,c.getAttr(plug)+v)
                else:
                    settings=p['zero_controls']['settings']
                    for a in 'XYZ':
                        attr='bipHipTranslate'+a
                        if c.objExists(settings+'.'+attr):
                            c.setAttr(settings+'.'+attr,c.attributeQuery(attr,node=settings,listDefault=True)[0])
                for role in ('heel','toe_end','ball'):
                    n=ctrl[role]
                    for a in TR:
                        plug=self.dst(n,a)
                        if not c.getAttr(plug,lock=True):c.setAttr(plug,-self.z.offset(plug))
                for role,i in [('foot',2),('toe',3)]:self.world(ctrl[role],self.offsets[ctrl[role]].inverse()*world[targets[i]])
                self.position(ctrl['knee'],om.MVector(pole))
            for joint,point in zip(p['joints'][:3],points[:3]):
                error=(om.MVector(c.xform(joint,q=True,ws=True,t=True))-point).length()
                if error>0.02:raise RuntimeError('IK 位置不匹配：{} {:.6f}'.format(joint,error))
        for driver,ctrl,t,offset,channel in self.orientation:
            self.le._world(driver,offset.inverse()*world[t],{driver+'.rotate'+a:ctrl+'.'+channel+a for a in 'XYZ'},False)

    def key(self,frame):
        c=self.c
        for p in self.plugs:
            c.setKeyframe(p,t=frame,v=c.getAttr(p),itt='linear',ott='step' if p in self.mode_plugs else 'linear')
        c.dgdirty(list({p.split('.')[0] for p in self.plugs}))

    def error(self,world):
        c=self.c
        return max(abs(a-b) for n,m in world.items() for a,b in zip(c.xform(n,q=True,ws=True,m=True),list(m)))


def retarget(data,root=None,reference_frame=None,start_frame=None,dry_run=False,overwrite=False,key_mode='source'):
    import maya.cmds as c
    from . import arm_ik
    import maya.api.OpenMaya as om
    data=read_data(data)
    if key_mode not in ('source','sampled'):raise ValueError('关键帧模式必须是 source 或 sampled。')
    job=plan(data,root,reference_frame,start_frame)
    key_times=None;schedules=None
    if key_mode=='source':
        from .bip_sparse import group_schedules
        schedules=group_schedules(data,om.MTime(1,om.MTime.kSeconds).asUnits(om.MTime.uiUnit()),job['frames'][0][0],job['rig']['parts'])
        key_times=sorted({t for times in schedules.values() for t in times})
    if dry_run:return dict(sample_count=len(job['frames']),mapping=job['mapping'],hips_source=data['root'],scale=job['scale'],native_adaptation=bool(job['native']),key_mode=key_mode,key_times=key_times,key_groups=schedules)
    if not c.undoInfo(q=True,state=True):raise ValueError('导入前需要开启 Maya 撤销功能。')
    if c.ls(type='animLayer'):raise ValueError('首版暂不写入含动画层的绑定，请先使用不含动画层的绑定副本。')
    auto=c.autoKeyframe(q=True,state=True);time=c.currentTime(q=True);busy=arm_ik._busy
    mode=c.evaluationManager(q=True,mode=True)[0];selection=c.ls(sl=True,long=True) or []
    c.autoKeyframe(state=False);arm_ik._busy=True
    c.undoInfo(openChunk=True,chunkName='BIPRetarget');success=False
    try:
        # Always put a real undoable operation in the private transaction;
        # failed preflight must never undo an earlier user edit.
        marker=c.createNode('network',name='bipRetargetTransaction',skipSelect=True)
        c.select(clear=True);c.evaluationManager(mode='off');c.currentTime(job['reference_frame'])
        baker=Baker(job)
        for p in baker.plugs:
            incoming=c.connectionInfo(_actual_plug(p),sfd=True)
            if incoming and (not c.nodeType(incoming.split('.')[0]).startswith('animCurve') or not overwrite):
                raise ValueError('控制器已有动画或外部驱动：'+p)
        backup=c.createNode('network',name=job['rig']['namespace']+':bipAnimationBackup',skipSelect=True)
        saved={};curves={}
        # Store curves and exact destination plugs before installing new nodes.
        for p in baker.plugs:
            p=_actual_plug(p)
            src=c.connectionInfo(p,sfd=True)
            saved[p]=dict(value=c.getAttr(p),source=src)
            if src and c.nodeType(src.split('.')[0]).startswith('animCurve'):
                node=src.split('.')[0]
                if node not in curves:curves[node]=c.duplicate(node,name=node+'_beforeBIP')[0]
        baker.initialize()
        for p in baker.plugs:
            actual=_actual_plug(p)
            if actual not in saved:saved[actual]=dict(value=c.getAttr(actual),source='')
        c.addAttr(backup,ln='originalAnimation',dt='string')
        c.setAttr(backup+'.originalAnimation',json.dumps(dict(plugs=saved,curves=curves)),type='string')
        # Replace only the explicitly selected interval, retaining outer keys.
        for p in baker.plugs:
            if c.connectionInfo(p,sfd=True):c.cutKey(p,time=(job['frames'][0][0],job['frames'][-1][0]),clear=True)
        maximum=0;samples=[];previous_angles={}
        angle_plugs=[p for p in baker.plugs if c.getAttr(p,type=True)=='doubleAngle']
        for f,world in job['frames']:
            c.currentTime(f)
            # Choose Euler solutions relative to the previously solved pose,
            # not to an old/future animation curve still driving this frame.
            # Do this before solving the body: its bend weights use Euler
            # values, so filtering body angles afterwards would change poses.
            for plug,value in previous_angles.items():c.setAttr(plug,value)
            baker.solve(world,job['com_frames'][f]);baker.key(f)
            previous_angles={p:c.getAttr(p) for p in angle_plugs}
            if key_times is not None:samples.append((f,{_actual_plug(p):c.getAttr(p) for p in baker.plugs}))
            e=baker.error(world);maximum=max(maximum,e)
            if e>0.02:raise RuntimeError('BIP 烘焙误差超限：帧 {}，{}'.format(f,e))
        for f,world in reversed(job['frames']):
            c.currentTime(f);e=baker.error(world);maximum=max(maximum,e)
            if e>0.02:raise RuntimeError('BIP 回放误差超限：帧 {}，{}'.format(f,e))
        sparse_error=None;sparse_rotation_error=None
        if key_times is not None:
            from .bip_sparse import apply
            apply(baker,samples,schedules)
            sparse_error=0;sparse_rotation_error=0
            for f,world in job['frames']:
                c.currentTime(f)
                for n,m in world.items():
                    actual=_matrix(c.xform(n,q=True,ws=True,m=True))
                    sparse_error=max(sparse_error,(_pos(actual)-_pos(m)).length())
                    qa=om.MTransformationMatrix(actual).rotation(asQuaternion=True)
                    qb=om.MTransformationMatrix(m).rotation(asQuaternion=True)
                    cosine=abs(qa.x*qb.x+qa.y*qb.y+qa.z*qb.z+qa.w*qb.w)
                    sparse_rotation_error=max(sparse_rotation_error,math.degrees(2*math.acos(min(1.,cosine))))
                # Independent groups no longer key every parent at every child
                # key. The resulting world error includes parent interpolation;
                # report it rather than silently borrowing another group's keys.
        c.delete(marker)
        success=True
        return dict(sample_count=len(job['frames']),start_frame=job['frames'][0][0],end_frame=job['frames'][-1][0],max_world_error=maximum,scale=job['scale'],backup=backup,hips_source=data['root'],native_adaptation=bool(job['native']),key_mode=key_mode,key_times=key_times,key_groups=schedules,max_sparse_position_error_cm=sparse_error,max_sparse_rotation_error_degrees=sparse_rotation_error,controls=sorted({p.split('.')[0] for p in baker.plugs}))
    finally:
        c.undoInfo(closeChunk=True)
        if not success:c.undo()
        c.currentTime(time);c.autoKeyframe(state=auto);c.evaluationManager(mode=mode)
        c.select(selection,replace=True) if selection else c.select(clear=True)
        arm_ik._busy=busy;arm_ik._sync_mode_cache()


def retarget_json(path,**kwargs):return retarget(path,**kwargs)


def retarget_max_bip(max_root='Bip001',bip_path=None,start_frame=None,end_frame=None,
                     sample_step=0.5,output_start=None,native_adaptation=True,
                     backend='auto',max_executable=None,progress=None,max_fps=30,**kwargs):
    """BIP files use isolated background Max; live capture remains opt-in in UI."""
    # One interior sample cannot recover two independent endpoint tangents in
    # a one-frame COM segment. Refine calculation only, never final key times.
    if kwargs.get('key_mode','source')=='source':sample_step=min(float(sample_step),.25)
    if backend not in ('auto','batch','live'):raise ValueError('backend 必须是 auto、batch 或 live。')
    if backend=='auto':backend='batch' if bip_path else 'live'
    if backend=='batch':
        if not native_adaptation:raise ValueError('后台文件导入需要开启 Max Biped 原生身材适配。')
        if not bip_path:raise ValueError('请选择 .bip 文件，后台导入无需 MCP。')
        from max_mcp.batch_client import capture
        profile=target_profile(kwargs.get('root'),kwargs.get('reference_frame'))
        data=capture(dict(root=max_root,bip_path=bip_path,profile=profile,
                         start=start_frame,end=end_frame,step=sample_step),
                     executable=max_executable,progress=progress,fps=max_fps)
        return retarget(data,start_frame=output_start,**kwargs)
    from max_mcp.connection import request
    if native_adaptation:
        profile=target_profile(kwargs.get('root'),kwargs.get('reference_frame'))
        data=request('retarget_biped',dict(root=max_root,bip_path=bip_path,profile=profile,
                     start=start_frame,end=end_frame,step=sample_step),timeout=600)
        return retarget(data,start_frame=output_start,**kwargs)
    if bip_path and kwargs.get('dry_run'):
        raise ValueError('检查映射不载入或替换 Max 动画，请先在 Max 打开 BIP 后清空文件路径再检查。')
    if bip_path and Path(bip_path).suffix.lower()!='.bip':raise ValueError('需要 .bip 文件。')
    if bip_path:request('load_bip',dict(root=max_root,file_path=str(Path(bip_path).resolve())))
    info=request('scene')
    data=request('capture_biped',dict(root=max_root,
        start=info['range'][0] if start_frame is None else start_frame,
        end=info['range'][1] if end_frame is None else end_frame,step=sample_step),timeout=600)
    return retarget(data,start_frame=output_start,**kwargs)


def restore_animation(backup):
    """Restore controller values/curves from a named BIP backup, undoably."""
    import maya.cmds as c
    from . import arm_ik
    saved=json.loads(c.getAttr(backup+'.originalAnimation'))
    for plug,entry in saved['plugs'].items():
        if not c.objExists(plug):raise ValueError('备份目标不存在：'+plug)
        if entry['source'] and entry['source'].split('.')[0] not in saved['curves']:
            raise ValueError('备份缺少原曲线：'+plug)
    busy=arm_ik._busy;arm_ik._busy=True
    c.undoInfo(openChunk=True,chunkName='RestoreBIPAnimation')
    try:
        for plug,entry in saved['plugs'].items():
            if entry['source']:
                original=entry['source'].split('.')[0]
                old=saved['curves'][original]
                clone=c.duplicate(old,name=old+'_restored')[0]
                if not c.connectionInfo(clone+'.input',sfd=True):c.connectAttr('time1.outTime',clone+'.input')
                c.connectAttr(clone+'.output',plug,force=True)
            else:
                incoming=c.connectionInfo(plug,sfd=True)
                if incoming:c.disconnectAttr(incoming,plug)
                c.setAttr(plug,entry['value'])
    finally:
        c.undoInfo(closeChunk=True);arm_ik._busy=busy;arm_ik._sync_mode_cache()
