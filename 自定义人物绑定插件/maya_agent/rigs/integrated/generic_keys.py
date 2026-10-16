"""Include space matching channels in Maya's native frame editing commands."""
TR=('tx','ty','tz','rx','ry','rz')


def expose_matches(control,data):
    """Hidden keyable proxies participate in S/cutKey/scaleKey and native undo."""
    import maya.cmds as c
    for i,node in enumerate(data['offsets']):
        for attr in TR:
            name='genericMatch%d_%s'%(i,attr);plug=control+'.'+name;source=node+'.'+attr
            if c.objExists(plug):
                # Maya may return long channel names for the same connection.
                if not c.isConnected(source,plug):raise ValueError('通用匹配代理已被其他连接占用：'+plug)
            else:c.addAttr(control,ln=name,proxy=source,keyable=True,hidden=True)


def clean_orphan_matches(owner):
    """Explicit repair of old hidden keys; retain baseline and valid mode frames."""
    import maya.cmds as c
    from .generic_objects import _data
    data=_data(owner);mode=data['global_plug']
    source=c.connectionInfo(mode,sfd=True)
    if source and not c.nodeType(source.split('.')[0]).startswith('animCurveT'):
        raise ValueError('模式含动画层或外部驱动，不能自动清理匹配帧。')
    valid=set(c.keyframe(mode,q=True,tc=True) or [])
    edits=[]
    for node in data['offsets']:
        for attr in TR:
            plug=node+'.'+attr;source=c.connectionInfo(plug,sfd=True)
            if not source:continue
            curve=source.split('.')[0]
            if not c.nodeType(curve).startswith('animCurveT'):
                raise ValueError('匹配通道含动画层或外部驱动：'+plug)
            times=c.keyframe(curve,q=True,tc=True) or []
            # The first value is the pre-switch rest value, even when the
            # public mode curve did not originally have a key at that frame.
            for t in times[1:]:
                if not any(abs(t-v)<1e-8 for v in valid):edits.append((curve,t))
    auto=c.autoKeyframe(q=True,state=True)
    c.undoInfo(openChunk=True,chunkName='CleanGenericOrphanMatchKeys');c.autoKeyframe(state=False)
    try:
        for curve,t in edits:c.cutKey(curve,time=(t,t),clear=True)
        return dict(removed_keys=len(edits),removed_frames=sorted({t for curve,t in edits}),mode_frames=sorted(valid))
    finally:c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)
