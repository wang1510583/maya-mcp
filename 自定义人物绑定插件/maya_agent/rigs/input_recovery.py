"""Restore registered local limb links left isolated in a recovery file.

Only missing links are restored. Curves and existing drivers are never replaced.
The interrupted pose is retained in the existing zero offset, not baked to keys.
"""
import json
import math
from . import scene_data


def repair(control):
    import maya.cmds as c
    if not c.objExists(control+'.zeroChannelData'):return None
    d=scene_data.read(control+'.zeroChannelData')
    live=d['source'];root=d['root']
    if not c.objExists(live+'.liveInput') or not c.objExists(root+'.liveAlignmentData'):return None
    linked=c.listConnections(live+'.liveInput',s=True,d=False) or []
    if len(linked)!=1:return None
    source=linked[0]
    missing=[a for a in d['offsets'] if not c.connectionInfo(source+'.'+a,sfd=True)]
    if not missing:return None
    registry=scene_data.read(root+'.liveAlignmentData')
    def same(a,b):return bool(a and b and c.ls(a,long=True)) and c.ls(a,long=True)==c.ls(b,long=True)
    if (not same(registry['controls'].get(d['role'],''),live)
            or not same(registry['inputs'].get(d['role'],''),source)):
        raise ValueError('恢复文件的输入登记不匹配，未自动重连：'+control)
    registered={e['source']:e['proxy'] for e in registry['entries']}
    rows=[]
    for attr in d['offsets']:
        dst=source+'.'+attr;expected=live+'.'+attr
        recorded=next((v for k,v in registered.items() if same(k,dst)),None)
        if not recorded or not same(recorded,expected):
            raise ValueError('恢复文件缺少可靠的原输入登记：'+dst)
        incoming=c.connectionInfo(dst,sfd=True)
        if incoming:
            if not c.isConnected(expected,dst):
                raise ValueError('输入已有其他驱动，未自动恢复：'+dst)
            continue
        edge=d['edges'][attr];node=edge.rsplit('.',1)[0]
        kind='animBlendNodeAdditiveDA' if attr.startswith('rotate') else 'animBlendNodeAdditiveDL'
        if (not c.objExists(edge) or c.nodeType(node)!=kind
                or not c.isConnected(edge,expected)
                or not c.isConnected(control+'.'+attr,node+'.inputA')
                or c.getAttr(node+'.weightA')!=1 or c.getAttr(node+'.weightB')!=1):
            raise ValueError('归零输入结构已改变，未自动恢复：'+dst)
        offset=node+'.inputB';old=c.getAttr(offset);value=c.getAttr(dst)
        if (c.connectionInfo(offset,sfd=True) or c.getAttr(offset,lock=True)
                or c.getAttr(dst,lock=True) or abs(old-d['offsets'][attr])>1e-7):
            raise ValueError('归零偏移无法安全恢复：'+dst)
        for n in (control,source,live,node):
            if c.referenceQuery(n,isNodeReferenced=True) or any(c.lockNode(n,q=True,lock=True)):
                raise ValueError('请在可编辑的绑定源文件中恢复断开的输入：'+dst)
        new=old+value-c.getAttr(expected)
        if not all(math.isfinite(v) for v in (old,new,value)):raise ValueError('输入包含无效数值：'+dst)
        rows.append(dict(dst=dst,expected=expected,offset=offset,old=old,new=new,value=value,attr=attr))
    ns=root.rsplit('|',1)[-1].rsplit(':',1)[0]
    joints=[ns+':joint'+str(i) for i in range(1,4 if registry['kind']=='arm' else 5)]
    nodes=[n for n in joints+[control,source] if c.objExists(n)]
    poses={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    raw=c.getAttr(control+'.zeroChannelData');updated=json.loads(raw)
    locked=c.getAttr(control+'.zeroChannelData',lock=True);auto=c.autoKeyframe(q=True,state=True)
    done=[]
    c.undoInfo(openChunk=True,chunkName='RecoverInterruptedLimbInputs')
    try:
        c.autoKeyframe(state=False)
        for row in rows:
            c.setAttr(row['offset'],row['new']);updated['offsets'][row['attr']]=row['new']
        c.setAttr(control+'.zeroChannelData',lock=False)
        c.setAttr(control+'.zeroChannelData',json.dumps(updated),type='string',lock=locked)
        for row in rows:c.connectAttr(row['expected'],row['dst']);done.append(row)
        c.dgdirty(nodes,allPlugs=True)
        error=max(abs(a-b) for n,m in poses.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('恢复输入未能保留姿态，已回退：'+control)
        return dict(control=control,connections=len(rows),max_pose_error=error)
    except Exception:
        for row in reversed(done):
            c.disconnectAttr(row['expected'],row['dst']);c.setAttr(row['dst'],row['value'])
        for row in rows:c.setAttr(row['offset'],row['old'])
        c.setAttr(control+'.zeroChannelData',lock=False)
        c.setAttr(control+'.zeroChannelData',raw,type='string',lock=locked)
        c.dgdirty(nodes,allPlugs=True)
        raise
    finally:
        c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)


def before_gesture(controls):
    """Recover before temporary gesture isolation, including a routed ankle."""
    import maya.cmds as c
    from . import live_edit
    if live_edit._gesture:raise RuntimeError('操作尚未结束，不能恢复临时断开的输入。')
    candidates=list(controls)
    for control in controls:
        d=scene_data.read(control+'.zeroChannelData')
        if d['part'].startswith('leg') and d['role'] in ('heel','toe_end','ball'):
            candidates.append(scene_data.read(d['root']+'.zeroPartData')['controls']['foot'])
    results=[];seen=set()
    for control in candidates:
        full=(c.ls(control,long=True) or [control])[0]
        if full in seen:continue
        seen.add(full);report=repair(control)
        if report:results.append(report)
    return results
