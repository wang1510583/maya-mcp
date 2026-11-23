"""Run deferred, outside an MCP undo chunk, to verify recovery undo and redo."""
def run(output):
    import json,traceback,uuid
    from pathlib import Path
    import maya.cmds as c
    from maya_agent.rigs import input_recovery,zero_channels
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True);auto=c.autoKeyframe(q=True,state=True)
    ns='_recoveryUndo_'+uuid.uuid4().hex[:6];report={}
    try:
        c.autoKeyframe(state=False);c.namespace(add=ns)
        root=c.createNode('transform',name=ns+':root')
        live=c.createNode('transform',name=ns+':live',parent=root)
        source=c.createNode('transform',name=ns+':source',parent=root)
        control=c.createNode('transform',name=ns+':control',parent=root)
        c.addAttr(live,ln='liveInput',at='message');c.connectAttr(source+'.message',live+'.liveInput')
        edges={};entries=[]
        for attr in zero_channels.TR:
            node=c.createNode('animBlendNodeAdditiveDA' if attr.startswith('rotate') else 'animBlendNodeAdditiveDL',name=ns+':offset_'+attr)
            c.setAttr(node+'.weightA',1);c.setAttr(node+'.weightB',1)
            c.connectAttr(control+'.'+attr,node+'.inputA');c.connectAttr(node+'.output',live+'.'+attr)
            edges[attr]=node+'.output';entries.append(dict(source=source+'.'+attr,proxy=live+'.'+attr))
            c.setAttr(source+'.'+attr,2)
        data=dict(source=live,root=root,role='foot',part='leg_R',offsets={a:0 for a in zero_channels.TR},edges=edges)
        registry=dict(kind='leg',inputs={'foot':source},controls={'foot':live},entries=entries)
        for node,attr,value in ((control,'zeroChannelData',data),(root,'liveAlignmentData',registry)):
            c.addAttr(node,ln=attr,dt='string');c.setAttr(node+'.'+attr,json.dumps(value),type='string',lock=True)
        raw=c.getAttr(control+'.zeroChannelData');r=input_recovery.repair(control)
        assert c.undoInfo(q=True,undoName=True)=='RecoverInterruptedLimbInputs'
        c.undo()
        assert all(not c.connectionInfo(source+'.'+a,sfd=True) for a in zero_channels.TR)
        assert c.getAttr(control+'.zeroChannelData')==raw
        assert c.undoInfo(q=True,redoName=True)=='RecoverInterruptedLimbInputs'
        c.redo()
        assert all(c.isConnected(live+'.'+a,source+'.'+a) for a in zero_channels.TR)
        assert all(abs(c.getAttr(source+'.'+a)-2)<1e-8 for a in zero_channels.TR)
        report=dict(passed=True,undo_redo=True,pose_error=r['max_pose_error'])
    except Exception:report=dict(passed=False,traceback=traceback.format_exc())
    finally:
        for node in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(node):c.delete(node)
        if c.namespace(exists=ns):c.namespace(removeNamespace=ns)
        c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        report['cleaned']=set(c.ls(long=True))==before
        Path(output).write_text(json.dumps(report,indent=2),encoding='utf-8')
