"""Explicit repair of a confirmed wrist-only hold; never runs on scene load."""
import json
import uuid
from pathlib import Path
import maya.cmds as c
from maya_agent.rigs import live_edit


def repair(part,start,end):
    if end<=start:raise ValueError('Invalid frame range')
    data=json.loads(c.getAttr(part['root']+'.liveAlignmentData'))
    if data['kind']!='arm':raise ValueError('Arm required')
    ns=part['namespace'];side=part['side'];wrist=data['controls']['end_fk']
    companions=[data['controls'][r] for r in ('shoulder_fk','middle_fk')]+[ns+':elb_'+side+'1']
    plugs=[n+'.'+a for n in companions+[wrist,ns+':hand_'+side+'1'] for a in live_edit.TR]
    plugs=[p for p in plugs if not c.getAttr(p,lock=True)]
    snapshot=live_edit._snapshot(plugs)
    time=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    joints=part['joints'];samples={};endpoints={};before={}
    outside=sorted(set([start-1,start-3,end+1,end+3]))
    backup=Path(__file__).resolve().parents[1]/'outputs'/'repair-backups'/('wrist-hold-'+uuid.uuid4().hex+'.json')
    c.autoKeyframe(state=False)
    c.undoInfo(openChunk=True,chunkName='RepairWristOnlyHold')
    try:
        for frame in outside+[start,end]:
            c.currentTime(frame)
            before[frame]={n:c.xform(n,q=True,ws=True,m=True) for n in joints}
            if frame in (start,end):endpoints[frame]={p:c.getAttr(p) for p in plugs}
        # This is a hold repair, not a general animation cleanup operation.
        error=max(abs(before[start][n][i]-before[end][n][i]) for n in joints
                  for i in (range(12,15) if n==joints[2] else range(16)))
        if error>1e-5:raise ValueError('Endpoints contain intended arm motion; refusing hold repair')
        for plug in plugs:
            if any(start<t<end for t in c.keyframe(plug,q=True,tc=True) or []):
                raise ValueError('Interior keys require individual review: '+plug)
        c.currentTime(end);desired=live_edit._frame(data['inputs']['end_fk'])
        backup.parent.mkdir(parents=True,exist_ok=True)
        backup.write_text(json.dumps(dict(scene=c.file(q=True,sn=True),root=part['root'],
            start=start,end=end,snapshot=snapshot,poses=before),ensure_ascii=False,indent=2),encoding='utf-8')
        changed=[]
        for node in companions:
            for attr in live_edit.TR:
                plug=node+'.'+attr
                if plug not in endpoints[start]:continue
                value=endpoints[start][plug]
                if abs(value-endpoints[end][plug])<1e-7:continue
                if end not in (c.keyframe(plug,q=True,tc=True) or []):
                    raise ValueError('Missing compensating endpoint key: '+plug)
                c.keyframe(plug,e=True,time=(end,end),valueChange=value);changed.append(plug)
        c.currentTime(start);c.currentTime(end)
        destinations={e['source']:e['proxy'] for e in data['entries']}
        live_edit._world(data['inputs']['end_fk'],desired,destinations)
        for axis in 'XYZ':
            plug=wrist+'.translate'+axis
            if abs(c.getAttr(plug)-endpoints[start][plug])>1e-5:
                raise ValueError('Wrist needs translation; refusing rotation-only repair')
            plug=wrist+'.rotate'+axis
            c.setKeyframe(plug,time=end,value=c.getAttr(plug))
        endpoint_error=0;outside_error=0;hold_error=0
        for frame in outside+[start,end]:
            c.currentTime(frame)
            error=max(abs(a-b) for n,m in before[frame].items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
            if frame in (start,end):endpoint_error=max(endpoint_error,error)
            else:outside_error=max(outside_error,error)
        for i in range(25):
            frame=start+(end-start)*i/24;c.currentTime(frame)
            for n in joints:
                matrix=c.xform(n,q=True,ws=True,m=True)
                error=max(abs(before[start][n][j]-matrix[j]) for j in (range(12,15) if n==joints[2] else range(16)))
                hold_error=max(hold_error,error)
        if max(endpoint_error,outside_error,hold_error)>1e-5:
            raise RuntimeError('Repair validation failed: '+str((endpoint_error,outside_error,hold_error)))
        return dict(backup=str(backup),changed_companion_channels=changed,endpoint_error=endpoint_error,
                    outside_error=outside_error,hold_error=hold_error,samples=25)
    except Exception:
        c.currentTime(time);live_edit._restore(snapshot)
        raise
    finally:
        c.currentTime(time);c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)
