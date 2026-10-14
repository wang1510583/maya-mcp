"""Explicit, backed-up repair of v1.8.6 historical rotation references.

Preserves authored key poses; intentionally rebuilds the faulty interpolation.
Never runs implicitly on scene load or playback.
"""
import json
import math
from pathlib import Path
import uuid


def repair_character(root, backup_directory):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import live_rotation as rotation
    from .live_edit import TR, _world, _frame
    rig=json.loads(c.getAttr(root+'.integratedRigData'))
    entries=[];joints=[];controls=set()
    for key,part in rig['parts'].items():
        controls.update(part['controls'].values());controls.update(part.get('live_controls',{}).values())
        if not key.startswith('arm') or not c.objExists(part['root']+'.liveAlignmentData'):continue
        live=json.loads(c.getAttr(part['root']+'.liveAlignmentData'))
        joints.extend(part['joints'])
        for role in ('shoulder_fk','middle_fk'):
            source=live['inputs'][role]
            if c.objExists(source+'.liveRotationData'):
                layers=json.loads(c.getAttr(source+'.liveRotationData'))['layers']
                entries.append(dict(root=part['root'],role=role,source=source,proxy=live['controls'][role],
                                    target=live['targets'][role],layers=layers,
                                    animated=bool(c.keyframe(live['controls'][role],at=list(TR),q=True,keyframeCount=True))))
    if not entries:return {'repaired':0}
    frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    selection=c.ls(sl=True,long=True) or []
    overrides={}
    for node in controls:
        for attr in c.listAttr(node,keyable=True,scalar=True) or []:
            plug=node+'.'+attr
            if not c.objExists(plug) or c.getAttr(plug,lock=True):continue
            incoming=c.connectionInfo(plug,sourceFromDestination=True)
            if incoming and not c.nodeType(incoming.split('.')[0]).startswith('animCurve'):continue
            value=c.getAttr(plug)
            if isinstance(value,(int,float,bool)):overrides[plug]=value
    current={e['source']:c.xform(e['source'],q=True,ws=True,m=True) for e in entries}
    current_joints={n:c.xform(n,q=True,ws=True,m=True) for n in joints}
    times=sorted(set(c.keyframe(list(controls),q=True,tc=True) or [frame]))
    folder=Path(backup_directory);folder.mkdir(parents=True,exist_ok=True)
    backup=folder/('before_rotation_repair_'+uuid.uuid4().hex+'.ma')
    c.file(str(backup),exportAll=True,type='mayaAscii',preserveReferences=True)
    samples={};poses={};constants={}
    c.undoInfo(openChunk=True,chunkName='RepairLegacyRotationAnimation')
    try:
        c.autoKeyframe(state=False)
        # If the animator already deleted this controller's keys, do not
        # resurrect motion from its historical references during migration.
        for e in entries:
            if e['animated']:continue
            for layer in e['layers']:
                for axis in 'XYZ':
                    plug=layer['reference']+'.rotate'+axis
                    src=c.connectionInfo(plug,sourceFromDestination=True)
                    if src and c.nodeType(src.split('.')[0]).startswith('animCurve'):
                        value=c.getAttr(plug);c.disconnectAttr(src,plug);c.setAttr(plug,value)
        for t in times:
            c.currentTime(t)
            samples[t]={};poses[t]={n:c.xform(n,q=True,ws=True,m=True) for n in joints}
            for e in entries:
                source=e['source'];world=om.MMatrix(c.xform(source,q=True,ws=True,m=True));target=_frame(e['target'])
                pivot=list(om.MPoint(*list(target)[12:15])*world.inverse())[:3]
                samples[t][source]=(list(world),pivot)
                if source not in constants:
                    first=e['layers'][0]
                    op=om.MMatrix(c.getAttr(first['old_op'])) if first['old_op'] else om.MMatrix(first['old_matrix'])
                    parent=op*om.MMatrix(c.getAttr(source+'.parentMatrix[0]'))
                    constants[source]=([math.degrees(v) for v in om.MTransformationMatrix(world*target.inverse()).rotation()],
                                       [math.degrees(v) for v in om.MTransformationMatrix(target*parent.inverse()).rotation()])
        removed=[]
        for e in reversed(entries):
            layers=e['layers']
            for i in reversed(range(len(layers))):
                entry=dict(layers[i]);entry['old_text']=json.dumps({'layers':layers[:i]}) if i else None
                removed.extend(n for n in entry['created'] if c.objExists(n))
                rotation.rollback(entry)
        for e in entries:
            rotation.ensure_pivots(e['root'],e['role'])
        for t in times:
            c.currentTime(t)
            for e in entries:
                source=e['source'];proxy=e['proxy'];world,pivot=samples[t][source]
                axis,orient=constants[source]
                for attr,value in zip(rotation.CHANNELS,pivot+axis+orient):c.setAttr(proxy+'.'+attr,value)
                m=om.MTransformationMatrix();m.setTranslation(om.MVector(*pivot),om.MSpace.kTransform)
                _world(source,m.asMatrix()*om.MMatrix(world),{source+'.'+a:proxy+'.'+a for a in TR})
                solve_error=max(abs(a-b) for a,b in zip(world,c.xform(source,q=True,ws=True,m=True)))
                if solve_error>1e-5:raise RuntimeError('Source solve error: '+str((t,source,solve_error)))
                for attr in TR+rotation.CHANNELS if e['animated'] else ():
                    plug=proxy+'.'+attr
                    if not c.getAttr(plug,lock=True):
                        c.setKeyframe(plug,time=t,value=c.getAttr(plug),inTangentType='auto',outTangentType='auto')
                key_error=max(abs(a-b) for a,b in zip(world,c.xform(source,q=True,ws=True,m=True)))
                if key_error>1e-5:raise RuntimeError('Source key error: '+str((t,source,key_error)))
        error=0;worst=None
        for t in times:
            c.currentTime(t)
            for n,m in poses[t].items():
                diff=max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
                if diff>error:error=diff;worst=(t,n)
        if error>1e-5:raise RuntimeError('Key pose repair error: '+str((error,worst))+'; backup '+str(backup))
        c.currentTime(frame)
        changed={e['proxy'] for e in entries}
        for plug,value in overrides.items():
            if plug.rsplit('.',1)[0] not in changed:c.setAttr(plug,value)
        for e in entries:
            source=e['source'];proxy=e['proxy']
            pivot=[c.getAttr(proxy+'.'+a) for a in rotation.PIVOTS]
            m=om.MTransformationMatrix();m.setTranslation(om.MVector(*pivot),om.MSpace.kTransform)
            _world(source,m.asMatrix()*om.MMatrix(current[source]),{source+'.'+a:proxy+'.'+a for a in TR})
        current_error=max(abs(a-b) for n,m in current_joints.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if current_error>1e-5:raise RuntimeError('Current pose repair error: '+str(current_error))
        report=dict(repaired=len(entries),layers_removed=sum(len(e['layers']) for e in entries),
                    nodes_removed=len(set(removed)),key_times=times,key_pose_error=error,current_pose_error=current_error,
                    backup=str(backup),interpolation='rebuilt_from_authored_key_poses')
        backup.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
    finally:
        if c.currentTime(q=True)!=frame:c.currentTime(frame)
        c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(cl=True)
        c.undoInfo(closeChunk=True)
