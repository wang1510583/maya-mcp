"""Matched upper-arm parent spaces, keying only at the current frame."""
import json

VERSION='1.0.0'


def _data(control):
    import maya.cmds as c
    return json.loads(c.getAttr(control+'.upperArmSpaceData'))


def enable(rig,space):
    import maya.cmds as c
    from . import foot_space,arm_ik,live_edit
    source=rig['controls']['shoulder_fk']
    if c.objExists(source+'.upperArmSpaceData'):
        rig['upper_arm_space']=_data(source)
        return rig['upper_arm_space']
    if space['control']!=source:raise ValueError('大臂空间与控制器不匹配。')
    control=rig.get('live_controls',{}).get('shoulder_fk',source)
    live_edit.install();auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    c.undoInfo(openChunk=True,chunkName='EnableMatchedUpperArmSpace');c.autoKeyframe(state=False);arm_ik._busy=True
    try:
        foot_space._enum(space['attribute'],control+'.global')
        data=dict(version=VERSION,root=rig['root'],source=source,control=control,
                  global_plug=space['attribute'],driver=space['driver'],group=space['group'],joints=rig['joints'])
        # Metadata belongs to this input, so wrist and upper-arm observers can
        # coexist on the same rig without sharing mode caches or undo entries.
        c.addAttr(source,ln='upperArmSpaceData',dt='string')
        c.setAttr(source+'.upperArmSpaceData',json.dumps(data),type='string',lock=True)
        rig['upper_arm_space']=data
        return data
    finally:
        arm_ik._busy=busy;c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True);arm_ik.install()


def _key_current(snapshot,plug,old):
    from .live_layers import key_mode_switch
    key_mode_switch(snapshot,plug)


def switch(control,value,key=None,previous=None):
    from .foot_space import _switch_data
    return _switch_data(_data(control),value,key,previous,_key_current,'大臂')


def enable_character(root):
    import maya.cmds as c
    rig=json.loads(c.getAttr(root+'.integratedRigData'));upgraded=[]
    c.undoInfo(openChunk=True,chunkName='EnableCharacterUpperArmSpaces')
    try:
        for key,part in rig['parts'].items():
            if not key.startswith('arm'):continue
            space=next((s for s in rig.get('spaces',[]) if s['control']==part['controls']['shoulder_fk']),None)
            if space:enable(part,space);upgraded.append(part['controls']['shoulder_fk'])
        c.setAttr(root+'.integratedRigData',lock=False)
        c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
    finally:c.undoInfo(closeChunk=True)
    return upgraded
