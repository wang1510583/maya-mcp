"""Matched chest global using four independent body-direction/space states."""
import json


def _data(control):
    import maya.cmds as c
    return json.loads(c.getAttr(control+'.chestSpaceData'))


def enable(rig):
    import maya.cmds as c
    from . import body_direction,arm_ik,foot_space,zero_channels
    hips=rig['controls']['hips'];chest=rig['controls']['chest']
    if not c.objExists(chest+'.global'):return None
    if c.objExists(chest+'.chestSpaceData'):return _data(chest)
    data=body_direction._data(hips);ns=rig['namespace'];created=[];added=[];rewired=[]
    original_data=c.getAttr(hips+'.bodyDriveData')
    originals=[hips+'.bodyMatchStart'+str(mode) for mode in (0,1)]
    originals += [p for entry in data['match_inputs'].values() for plugs in entry['offsets'].values() for p in plugs]
    for plug in originals:
        edge=c.connectionInfo(plug,sfd=True)
        if edge and not c.nodeType(edge.split('.')[0]).startswith('animCurve'):
            raise ValueError('未知的身体补偿输入：'+plug)
    busy=arm_ik._busy;arm_ik._busy=True
    def node(kind,label):
        n=c.createNode(kind,name=ns+':chestMatch_'+label,skipSelect=True);created.append(n);return n
    def clone_value(old,new):
        c.addAttr(new.rsplit('.',1)[0],ln=new.rsplit('.',1)[1],at='double',hidden=True)
        added.append(new)
        c.setAttr(new,c.getAttr(old))
        edge=c.connectionInfo(old,sfd=True)
        if edge:
            source=edge.split('.')[0]
            if not c.nodeType(source).startswith('animCurve'):
                raise ValueError('未知的身体补偿输入：'+old)
            duplicate=c.duplicate(source,name=source+'_chest')[0];created.append(duplicate)
            incoming=c.connectionInfo(source+'.input',sfd=True)
            if incoming:c.connectAttr(incoming,duplicate+'.input',force=True)
            c.connectAttr(duplicate+'.output',new)
    try:
        foot_space._enum(chest+'.global',zero_channels.surface(chest)+'.global')
        mul=node('multDoubleLinear','mode');c.connectAttr(chest+'.global',mul+'.input1');c.setAttr(mul+'.input2',2)
        add=node('addDoubleLinear','state');c.connectAttr(hips+'.bodyDrive',add+'.input1');c.connectAttr(mul+'.output',add+'.input2')
        starts={}
        for mode in (2,3):
            start=hips+'.bodyMatchStart'+str(mode);clone_value(hips+'.bodyMatchStart'+str(mode-2),start);starts[mode]=start
        for i,(ctrl,entry) in enumerate(data['match_inputs'].items()):
            gates={}
            for mode in (2,3):
                g=node('condition','time%d_%d'%(i,mode));gates[mode]=g
                c.setAttr(g+'.operation',3);c.connectAttr('time1.outTime',g+'.firstTerm');c.connectAttr(starts[mode],g+'.secondTerm')
                c.setAttr(g+'.colorIfTrueR',1);c.setAttr(g+'.colorIfFalseR',0)
            for channel in ('translate','rotate'):
                for mode in (2,3):entry['offsets'][str(mode)+channel]=[]
                for axis,old in zip('XYZ',entry['offsets']['0'+channel]):
                    gate=c.listConnections(old,s=False,d=True,type='multDoubleLinear')[0]
                    choice=c.listConnections(gate+'.output',s=False,d=True,type='choice')[0]
                    rewired.append((c.connectionInfo(choice+'.selector',sfd=True),choice+'.selector'))
                    c.connectAttr(add+'.output',choice+'.selector',force=True)
                    for mode in (2,3):
                        p=ctrl+'.bodyMatch'+str(mode)+channel.title()+axis
                        clone_value(ctrl+'.bodyMatch'+str(mode-2)+channel.title()+axis,p)
                        entry['offsets'][str(mode)+channel].append(p)
                        g=node('multDoubleLinear','%d_%s%s_%d'%(i,channel,axis,mode))
                        c.connectAttr(p,g+'.input1');c.connectAttr(gates[mode]+'.outColorR',g+'.input2')
                        c.connectAttr(g+'.output',choice+'.input[%d]'%mode)
            # Entries are persisted once every selector has all four inputs.
        data['chest_global']=chest+'.global';data['created'].extend(created)
        c.setAttr(hips+'.bodyDriveData',lock=False);c.setAttr(hips+'.bodyDriveData',json.dumps(data),type='string',lock=True)
        result=dict(root=rig['root'],body=hips,control=chest,global_plug=chest+'.global',created=created)
        c.addAttr(chest,ln='chestSpaceData',dt='string');c.setAttr(chest+'.chestSpaceData',json.dumps(result),type='string',lock=True)
        rig['chest_space']=result;rig.setdefault('nodes',[]).extend(created)
        return result
    except Exception:
        for src,dst in reversed(rewired):c.connectAttr(src,dst,force=True)
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        for p in reversed(added):
            if c.objExists(p):c.deleteAttr(p)
        if c.objExists(chest+'.chestSpaceData'):
            c.setAttr(chest+'.chestSpaceData',lock=False);c.deleteAttr(chest+'.chestSpaceData')
        c.setAttr(hips+'.bodyDriveData',lock=False);c.setAttr(hips+'.bodyDriveData',original_data,type='string',lock=True)
        raise
    finally:
        arm_ik._busy=busy
        if c.objExists(chest+'.chestSpaceData'):arm_ik.install()


def switch(control,value,key=None,previous=None):
    from .body_direction_match import switch as match
    data=_data(control)
    return match(data['body'],value,key=key,previous=previous,mode_plug=data['global_plug'])
