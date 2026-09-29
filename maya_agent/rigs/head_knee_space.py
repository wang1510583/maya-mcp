"""Pose-preserving head and knee spaces on the original controls."""
import json

VERSION='1.0.0'


def _data(control):
    import maya.cmds as c
    return json.loads(c.getAttr(control+'.matchedSpaceData'))


def enable(rig,space,role):
    import maya.cmds as c
    from . import foot_space,arm_ik,live_edit
    if role not in ('head','knee'):raise ValueError('Unsupported matched space: '+role)
    source=rig['controls'][role]
    if space['control']!=source:raise ValueError('空间与控制器不匹配。')
    if c.objExists(source+'.matchedSpaceData'):
        data=_data(source);rig.setdefault('matched_spaces',{})[role]=data;return data
    control=rig.get('live_controls',{}).get(role,source)
    nodes=list(rig.get('joints',[]))+list(rig.get('output_frames',[]))
    nodes += [m['target'] for m in rig.get('original_target_mapping',[])]
    nodes=list(dict.fromkeys(n for n in nodes if c.objExists(n)))
    if not nodes:raise ValueError('Missing output nodes for space validation')
    live_edit.install();auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    c.undoInfo(openChunk=True,chunkName='EnableMatchedHeadKneeSpace');c.autoKeyframe(state=False);arm_ik._busy=True
    try:
        foot_space._enum(space['attribute'],control+'.global')
        data=dict(version=VERSION,root=rig['root'],source=source,control=control,role=role,
                  global_plug=space['attribute'],driver=space['driver'],group=space['group'],joints=nodes)
        # Head translation is driven by neck position. Match its editable
        # additive offset instead of detaching or overriding that constraint.
        if role=='head':
            data['destinations']={source+'.translate'+a:source+'.positionOffset'+a for a in 'XYZ' if c.objExists(source+'.positionOffset'+a)}
        c.addAttr(source,ln='matchedSpaceData',dt='string')
        c.setAttr(source+'.matchedSpaceData',json.dumps(data),type='string',lock=True)
        rig.setdefault('matched_spaces',{})[role]=data
        return data
    finally:
        arm_ik._busy=busy;c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True);arm_ik.install()


def _key(snapshot,plug,old):
    from .live_layers import key_mode_switch
    key_mode_switch(snapshot,plug)


def switch(control,value,key=None,previous=None):
    from .foot_space import _switch_data
    data=_data(control)
    return _switch_data(data,value,key,previous,_key,'头部' if data['role']=='head' else '膝盖')


def enable_character(root):
    import maya.cmds as c
    rig=json.loads(c.getAttr(root+'.integratedRigData'));upgraded=[]
    c.undoInfo(openChunk=True,chunkName='EnableCharacterHeadKneeSpaces')
    try:
        for key,part in rig['parts'].items():
            role='head' if key=='head' else 'knee' if key.startswith('leg') else None
            if not role:continue
            space=next((s for s in rig.get('spaces',[]) if s['control']==part['controls'][role]),None)
            if space:enable(part,space,role);upgraded.append(part['controls'][role])
        c.setAttr(root+'.integratedRigData',lock=False)
        c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
    finally:c.undoInfo(closeChunk=True)
    return upgraded
