"""Fit the leg to ordered hip, knee, ankle and toe targets, without rebinding skin."""
import json
import math


def inspect(targets,allow_animation=False):
    import maya.cmds as c
    from maya_agent.rigs.custom_body.targets import inspect as inspect_targets
    if not isinstance(targets,(list,tuple)) or len(targets)!=4:
        raise ValueError('请依次选择 4 个骨骼或物体：髋 → 膝 → 踝 → 脚趾。')
    samples,_=inspect_targets(targets,allow_animation=allow_animation)
    for sample in samples:
        sample['position']=c.xform(sample['node'],q=True,ws=True,rp=True)
        node=sample['node']
        while node:
            for attr in ('scale','shear','rotateAxis','rotatePivot','scalePivot','jointOrient','rotateOrder'):
                if allow_animation and attr=='scale':continue
                for plug in [node+'.'+attr]+[node+'.'+attr+a for a in 'XYZ']:
                    if c.objExists(plug) and c.listConnections(plug,s=True,d=False):
                        raise ValueError('目标或父级已有动画/驱动，未覆盖：'+plug)
            parents=c.listRelatives(node,parent=True,fullPath=True) or []
            node=parents[0] if parents else None
    lengths=[math.dist(a['position'],b['position']) for a,b in zip(samples,samples[1:])]
    if min(lengths)<1e-5 or math.dist(samples[0]['position'],samples[2]['position'])<1e-5:
        raise ValueError('相邻关节或髋踝位置重合，无法创建腿部求解器。')
    return samples,lengths


def fit(rig,samples,lengths):
    import maya.cmds as c
    from maya_agent.rigs.soft_limb.selection import _geometry
    from .adjustment import set_pivot,sync_guides
    ns=rig['namespace']+':'
    hip,knee,ankle,toe=[s['position'] for s in samples]
    _,pole,straight=_geometry(samples[:3])
    for i,length in enumerate(lengths[:2],1):
        c.setAttr(ns+'strech_ik_foot1_L1.lenght_joint_'+str(i),length)
    c.xform(ns+'joint1',ws=True,t=hip)
    # Foot local X is the rolling axis; its world heading follows ankle -> toe.
    direction=[b-a for a,b in zip(ankle,toe)]
    heading=math.degrees(math.atan2(direction[0],direction[2]))
    c.xform(ns+'foot_L1',ws=True,rotation=(-90,heading,0))
    set_pivot(ns+'foot_L1',ankle)
    set_pivot(ns+'tarsus_L1',toe)
    set_pivot(ns+'ik_connect_L1',ankle)
    for key,ratio in (('heel_L1',-.5),('toe_end_L1',1.5),('toe_L1',.8)):
        point=[a+ratio*d for a,d in zip(ankle,direction)]
        point[1]=0.0
        set_pivot(ns+key,point)
    c.xform(ns+'Knee_L',ws=True,t=pole)
    c.xform(ns+'joint4',ws=True,t=toe)
    for sample,joint in zip(samples,rig['joints']):
        error=math.dist(c.xform(joint,q=True,ws=True,t=True),sample['position'])
        if error>max(sum(lengths)*1e-6,1e-5):
            raise RuntimeError('腿部匹配失败：{}，误差 {}'.format(joint,error))
    size=sum(lengths[:2])/5.467700044062811
    for shape in c.ls(ns+'*',type='locator') or []:
        for axis in 'XYZ':c.setAttr(shape+'.localScale'+axis,c.getAttr(shape+'.localScale'+axis)*size)
    for joint in c.ls(ns+'*',type='joint') or []:
        c.setAttr(joint+'.radius',c.getAttr(joint+'.radius')*size)
    sync_guides(rig)
    c.addAttr(rig['root'],ln='legTargets',dt='string')
    c.setAttr(rig['root']+'.legTargets',json.dumps([s['node'] for s in samples]),type='string',lock=True)
    rig.update(lengths=lengths,mode='selection',straight_input=straight,
               warnings=['髋膝踝共线，已生成默认膝盖方向，可移动膝盖控制器调整。'] if straight else [])


def build_from_selection(targets=None,namespace='customLeg',drive_targets=True,copy_animation=False,
                         start_frame=None,end_frame=None,sample_step=1.0,side='L'):
    import maya.cmds as c
    from . import _build_template,cleanup
    from .adjustment import edit_chunk
    from maya_agent.rigs.soft_limb.selection import connect
    from maya_agent.rigs.custom_body.targets import restore
    from maya_agent.rigs.custom_body.animation import frame_range
    from maya_agent.rigs.soft_limb import sides
    sides.validate(side)
    if not isinstance(drive_targets,bool):raise ValueError('drive_targets 必须是布尔值')
    if not isinstance(copy_animation,bool):raise ValueError('copy_animation 必须是布尔值')
    if copy_animation and not drive_targets:raise ValueError('拷贝动画需要勾选驱动所选物体。')
    frames=frame_range(c.playbackOptions(q=True,minTime=True) if start_frame is None else start_frame,
                       c.playbackOptions(q=True,maxTime=True) if end_frame is None else end_frame,
                       sample_step) if copy_animation else []
    if targets is None:
        if not c.selectPref(q=True,trackSelectionOrder=True):
            raise ValueError('请先打开腿部系统窗口，再按髋、膝、踝、脚趾的顺序重新选择。')
        targets=c.ls(orderedSelection=True,long=True) or []
    samples,lengths=inspect(targets,allow_animation=copy_animation)
    selection=c.ls(sl=True,long=True) or []
    rig=None
    transfer=None
    with edit_chunk('CreateLegFromSelection'):
        try:
            rig=_build_template(namespace=namespace)
            fit(rig,samples,lengths)
            if copy_animation:
                from .animation import Transfer
                transfer=Transfer(rig,samples,frames)
                transfer.capture()
                transfer.detach()
                drivers=transfer.prepare_drivers()
                rig['target_mapping']=connect(rig,samples,drivers=drivers)
            else:rig['target_mapping']=connect(rig,samples) if drive_targets else []
            rig['animation_transfer']=transfer.bake(rig['target_mapping']) if transfer else None
            rig['drive_targets']=drive_targets
            rig['nodes']=c.ls(rig['namespace']+':*',long=True)
            sides.apply(rig,side,metadata_attr='legSide')
            data=json.loads(c.getAttr(rig['root']+'.legSetupData'))
            data['controls']={k:rig['controls'][k] for k in data['controls']}
            c.setAttr(rig['root']+'.legSetupData',lock=False)
            c.setAttr(rig['root']+'.legSetupData',json.dumps(data),type='string',lock=True)
            return rig
        except Exception:
            if transfer:transfer.release_backup()
            if rig:cleanup(rig['namespace'])
            if transfer:transfer.rollback()
            elif not copy_animation:restore(samples)
            raise
        finally:
            if transfer:c.currentTime(transfer.time)
            existing=[n for n in selection if c.objExists(n)]
            c.select(existing,r=True) if existing else c.select(clear=True)
