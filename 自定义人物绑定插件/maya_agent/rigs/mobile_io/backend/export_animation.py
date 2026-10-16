"""Sample the current rig animation and independent Maya output references.

Only time is changed. Curves, connections and rig construction remain untouched.
The portable graph must be validated against every emitted frame before shipping.
"""
import json, math, runpy, hashlib
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

ATTRS=('rotateX','rotateY','rotateZ','translateX','translateY','translateZ')

def export(snapshot_path, graph_path, destination, reference_path):
    raw=Path(snapshot_path).read_bytes();snap=json.loads(raw.decode('utf8'))
    graph=json.loads(Path(graph_path).read_text(encoding='utf8'))
    assert graph['sourceSnapshotSha256']==hashlib.sha256(raw).hexdigest()
    for path in (destination,reference_path):
        if Path(path).exists():raise FileExistsError(str(path))
    fp=runpy.run_path(str(Path(__file__).with_name('export_snapshot.py')))['fingerprint']
    before=fp()
    nodes=c.ls(type='transform',long=True)+c.ls(type='joint',long=True)
    matrices={n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    edges=sorted(c.listConnections(nodes,c=True,p=True,s=True,d=False) or [])
    inputs=[o for o in graph['ops'] if o['op']=='input']
    labels={r['part']+'/'+r['role']:r['id'] for r in snap['controls']}
    reverse={v:k for k,v in labels.items()}
    controls={r['id']:c.ls(r.get('nodeId',r['id']),long=True)[0] for r in snap['controls']}
    joints={r['id']:c.ls(r['id'],long=True)[0] for r in snap['joints']}
    meshes={}
    for m in snap['meshes']:
        sel=om.MSelectionList();sel.add(c.ls(m['id'],long=True)[0]);meshes[m['id']]=om.MFnMesh(sel.getDagPath(0))
    def outputs():
        out={'controls':{uid:c.xform(n,q=True,ws=True,m=True) for uid,n in controls.items()},
             'joints':{uid:c.xform(n,q=True,ws=True,m=True) for uid,n in joints.items()},'vertices':{}}
        for uid,fn in meshes.items():
            points=fn.getPoints(om.MSpace.kWorld)
            out['vertices'][uid]={str(i):[points[i].x,points[i].y,points[i].z] for i in range(0,len(points),max(1,len(points)//200))}
        return out
    start,end=map(int,snap['frameRange'])
    if start<0 or end>100000 or list(snap['frameRange'])!=[start,end]:raise ValueError('Current integer-frame format requires nonnegative integral playback bounds')
    unit=c.currentUnit(q=True,time=True)
    fps={'film':24,'pal':25,'ntsc':30,'show':48,'palf':50,'ntscf':60}.get(unit)
    if fps is None and unit.endswith('fps'):fps=float(unit[:-3])
    if fps is None:raise ValueError('Unsupported time unit '+unit)
    baseline=outputs();keys=[];cases=[];markers={};source_curves={}
    capture_curve=runpy.run_path(str(Path(__file__).with_name('animation_curves.py')))['capture']
    for op in inputs:
        uid=op['data']['id'];attr=ATTRS[op['data']['axis']];plug=op['name']
        curve=capture_curve(plug);times=curve['times']
        markers.setdefault(uid,set()).update(t for t in times if start<=t<=end)
        source_curves.setdefault(uid,{})[attr]=curve
    try:
        for frame in range(start,end+1):
            c.currentTime(frame,edit=True)
            values={}
            for op in inputs:
                d=op['data'];axis=d['axis'];base=d['base']*(180/math.pi if axis<3 else 1)
                values.setdefault(d['id'],{})[ATTRS[axis]]=c.getAttr(op['name'])-base
            keys.append({'frame':frame,'values':values})
            cases.append({'name':'frame-'+str(frame),'inputs':{reverse[uid]:v for uid,v in values.items()},'outputs':outputs()})
    finally:
        c.currentTime(before['frame'],edit=True)
        # Re-evaluate constraint and IK outputs after restoring time.
        try:c.dgdirty(allPlugs=True)
        except Exception:pass
        c.refresh(force=True)
        c.file(modified=before['modified'])
    after=fp()
    matrix_error=max(abs(a-b) for n,m in matrices.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
    edges_after=sorted(c.listConnections(nodes,c=True,p=True,s=True,d=False) or [])
    restored=all(before[k]==after[k] for k in before if k!='transformsHash') and matrix_error<1e-8 and edges==edges_after
    report={'sceneRestored':restored,'fingerprintExact':before==after,'matrixRestorationError':matrix_error,'connectionsRestored':edges==edges_after,'differences':[k for k in before if before[k]!=after[k]]}
    Path(reference_path).with_suffix('.restore.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    if not restored:raise RuntimeError('Scene restore failed '+str(report))
    step_ids=[]
    for cfg in graph.get('modePanel',{}).values():
        markers.setdefault(cfg['id'],set()).add(start);step_ids.append(cfg['id'])
        if cfg['kind']=='generic':
            ids=[f['id'] for f in cfg['frames']];step_ids+=ids
            markers.setdefault(cfg['controlId'],set()).update(t for uid in [cfg['id']]+ids for t in markers.get(uid,set()))
    animation={'format':'maya-mobile-animation','schemaVersion':1,'characterId':snap['characterId'],'rigVersion':snap['rigVersion'],
        'source':'maya-sampled-export','frame':start,'fps':fps,'interpolation':'linear','valueSpace':'snapshot-local-delta',
        'sourceSnapshotSha256':graph['sourceSnapshotSha256'],'sourceFrame':snap['sourceFrame'],'frameRange':[start,end],
        'curvePayloadVersion':1,
        'sampling':{'step':1,'sourceTimeUnit':unit,'originalCurveTangentsPreserved':True},
        'keyMarkers':{uid:sorted(times) for uid,times in markers.items()},'sourceCurves':source_curves,'keys':keys,
        'stepControls':step_ids}
    fixture={'labels':labels,'baseline':baseline,'cases':cases,**report}
    Path(destination).write_text(json.dumps(animation,separators=(',',':'),allow_nan=False),encoding='utf8')
    Path(reference_path).write_text(json.dumps(fixture,separators=(',',':'),allow_nan=False),encoding='utf8')
    return dict(frames=len(keys),range=[start,end],fps=fps,controls=len(keys[0]['values']),inputs=len(inputs),**report)
