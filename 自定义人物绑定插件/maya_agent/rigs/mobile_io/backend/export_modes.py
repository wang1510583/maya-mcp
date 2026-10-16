"""Registered character modes and their editable inputs. Read-only Maya export."""
import json
import maya.cmds as c
import maya.api.OpenMaya as om
TR=('rotateX','rotateY','rotateZ','translateX','translateY','translateZ')
IDENTITY=[1.,0,0,0,0,1.,0,0,0,0,1.,0,0,0,0,1.]

def canonical(plug):
    s=om.MSelectionList();s.add(plug);p=s.getPlug(0)
    # Attribute proxies share the actual underlying MPlug.
    return p.name()

def extend_snapshot(snap):
    from maya_agent.rigs import switch_panel,arm_ik
    metadata=snap['rigMetadata'];modes={}
    existing={canonical(row['path']+'.'+a) for row in snap['controls'] for a in TR}
    def row(node,uid,role,plugs):
        node=c.ls(node,long=True)[0];channels={}
        for a,p in zip(TR,plugs):
            if p:channels[a]=dict(value=c.getAttr(p),locked=c.getAttr(p,lock=True))
        data=dict(id=uid,nodeId=c.ls(node,uuid=True)[0],role=role,part='internal',path=node,name=node.rsplit('|',1)[-1],
            position=c.xform(node,q=True,ws=True,t=True),worldMatrix=c.xform(node,q=True,ws=True,m=True),
            rotateOrder=c.getAttr(node+'.rotateOrder'),channels=channels,curves=[],visible=False,inputOnly=True,inputPlugs=plugs)
        snap['controls'].append(data)
        return uid
    def scalar(plug,role):
        plug=canonical(plug);node,attr=plug.rsplit('.',1)
        uid=c.ls(node,uuid=True)[0]+'.'+attr
        if not any(r['id']==uid for r in snap['controls']):
            axis=0 if c.getAttr(plug,type=True)=='doubleAngle' else 3
            plugs=[None]*6;plugs[axis]=plug;row(node,uid,role,plugs)
        return uid
    for key,entry in switch_panel.targets(metadata).items():
        data=arm_ik._switch_module(entry['owner'])._data(entry['owner'])
        cfg=dict(role=key,owner=entry['owner'],data=data,id=scalar(data['global_plug'],'mode_'+key),base=c.getAttr(data['global_plug']))
        if key.startswith('wrist_'):
            cfg['ikIds']={}
            for role,node in data['controls'].items():
                uid=c.ls(node,uuid=True)[0];cfg['ikIds'][role]=uid
                if not any(r['id']==uid for r in snap['controls']):row(node,uid,key+'_'+role,[node+'.'+a for a in TR])
            cfg['stretchId']=scalar(data['stretch_plug'],key+'_stretch')
            cfg['offsetIds']=[scalar(p,key+'_offset') for p in data['offset_attrs']]
            cfg['offsetInputIds']=[scalar(p,key+'_offsetInput') for p in data['offset_inputs']]
        elif key.startswith('generic_'):
            cfg['offsetIds']=[]
            for i,node in enumerate(data['offsets']):
                uid=c.ls(node,uuid=True)[0]
                cfg['offsetIds'].append(row(node,uid,key+'_match'+str(i),[node+'.'+a for a in TR]))
        modes[key]=cfg
    snap['modePanel']=modes

def compile_modes(snap,cc):
    from maya_agent.rigs import zero_channels
    destinations={}
    for part in snap['rigMetadata']['parts'].values():
        if c.objExists(part['root']+'.liveAlignmentData'):
            destinations.update({e['source']:e['proxy'] for e in json.loads(c.getAttr(part['root']+'.liveAlignmentData'))['entries']})
    def editable_plug(p):return zero_channels.resolve(destinations.get(p,p))
    def get(n,a):return cc.get(n+'.'+a)
    def input_ref(plug):
        name=cc.name(cc.plug(editable_plug(plug)))
        if name in cc.inputs:return cc.inputs[name]
        # Live surface channels can be proxies of the registered zero control.
        p=cc.plug(editable_plug(plug))
        for _ in range(8):
            if not p.isDestination:break
            p=p.source()
            name=cc.name(p)
            if name in cc.inputs:return cc.inputs[name]
        return None
    def frame(node,uid=None):
        refs=[input_ref(node+'.'+a) for a in TR]
        if uid is None:
            ids={r[0] for r in refs if r}
            if len(ids)!=1:raise ValueError('Unregistered mode input '+node+': '+str(refs))
            uid=next(iter(ids))
        return dict(id=uid,world=get(node,'worldMatrix[0]'),local=get(node,'matrix'),parent=get(node,'parentMatrix[0]'),
            editable=[r is not None and r[0]==uid for r in refs])
    result={};aliases={}
    for key,source in snap.get('modePanel',{}).items():
        d=source['data'];cfg={k:source[k] for k in ('id','base','role')}
        cfg['guards']=[get(n,'worldMatrix[0]') for n in d.get('joints',[])]
        if key in ('hips','chest'):
            from maya_agent.rigs import body_direction
            body=d if key=='hips' else body_direction._data(d['body'])
            if not body.get('fixed_zero'):raise ValueError('Body mode export requires fixed zero controls')
            cfg.update(kind='body',frames=[frame(n) for n in body['controls']],driveId=snap['modePanel']['hips']['id'],driveBase=snap['modePanel']['hips']['base'])
            cfg['guards']=[get(n,'worldMatrix[0]') for n in body['controls']+body['joints']]
        elif key.startswith('wrist_'):
            cfg.update(kind='arm',ikFrames={r:frame(n,source['ikIds'][r]) for r,n in d['controls'].items()},
                fkFrames={r:frame(d['inputs'][r]) for r in ('end_fk','end_locator','pole_locator')},
                end=get(d['inputs']['end_locator'],'worldMatrix[0]'),endJoint=get(d['joints'][-1],'worldMatrix[0]'),
                reach=cc.get(d['reach_plug']),stretchId=source['stretchId'],stretchBase=c.getAttr(d['stretch_plug']))
            cfg['reset']=[-zero_channels.offset(editable_plug(d['inputs']['end_locator']+'.'+a))-c.getAttr(editable_plug(d['inputs']['end_locator']+'.'+a)) for a in TR]
            if d['offset_attrs']:raise ValueError('Arm animation offsets need explicit mobile matching: '+d['root'])
            roles={'end_fk':'wrist','pole_locator':'pole'}
            part=snap['rigMetadata']['parts']['arm_'+key[-1]]
            for visible_role,ik_role in roles.items():
                visible=next(r for r in snap['controls'] if r['part']=='arm_'+key[-1] and r['role']==visible_role)
                aliases[visible['id']]=dict(modeId=source['id'],base=source['base'],frame=cfg['ikFrames'][ik_role])
        elif key.startswith('generic_'):
            frames=[]
            for i,node in enumerate(d['offsets']):
                f=frame(node,source['offsetIds'][i])
                # Maya stores a local match matrix on a hidden transform, but
                # applies it under the selected parent space through OPM.
                f['world']=get(d['compensation'],'worldMatrix[0]')
                f['parent']=get(d['group'],'worldMatrix[0]')
                frames.append(f)
            control=c.ls(d['control_uuid'],long=True)[0];target=c.ls(d['target_uuid'],long=True)[0]
            cfg.update(kind='generic',frames=frames,controlId=d['control_uuid'])
            cfg['guards']=[get(control,'worldMatrix[0]'),get(target,'worldMatrix[0]')]
        else:cfg.update(kind='space',frame=frame(d['source']))
        result[key]=cfg
    return result,aliases

def remap_modes(graph,visit):
    def frame(row):
        for key in ('world','local','parent'):row[key]=visit(row[key])
    for cfg in graph.get('modePanel',{}).values():
        cfg['guards']=[visit(i) for i in cfg['guards']]
        if cfg['kind']=='space':frame(cfg['frame'])
        elif cfg['kind'] in ('body','generic'):
            for f in cfg['frames']:frame(f)
        else:
            for f in list(cfg['ikFrames'].values())+list(cfg['fkFrames'].values()):frame(f)
            for key in ('end','endJoint','reach'):cfg[key]=visit(cfg[key])
    for cfg in graph.get('ikAliases',{}).values():frame(cfg['frame'])
