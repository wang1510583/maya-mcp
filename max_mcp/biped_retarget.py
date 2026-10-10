"""Load BIP through a temporary, proportion-matched native Max Biped."""
import math
import tempfile
import uuid
from pathlib import Path

PAIRS=[('Pelvis','Spine'),('Spine','Spine1'),('Spine1','Spine2'),
       ('Spine2','Neck'),('Neck','Head')]
for _s in ('L','R'):
    PAIRS.extend((_s+' '+a,_s+' '+b) for a,b in
                 [('Clavicle','UpperArm'),('UpperArm','Forearm'),('Forearm','Hand'),
                  ('Thigh','Calf'),('Calf','Foot'),('Foot','Toe0')])


def validate_profile(profile):
    points=profile['points']
    for name in {n for pair in PAIRS for n in pair}:
        p=points.get(name)
        if not isinstance(p,(list,tuple)) or len(p)!=3 or not all(math.isfinite(float(v)) for v in p):
            raise ValueError('Invalid target Figure point: '+name)
    for a,b in PAIRS+[('L Thigh','R Thigh'),('L Clavicle','R Clavicle')]:
        if math.dist(points[a],points[b])<1e-4:
            raise ValueError('Coincident target Figure points: '+a+' / '+b)
    return points


def capture(params):
    from pymxs import runtime as rt, attime
    from .max_adapter import _node, _samples
    points=validate_profile(params['profile'])
    source=None if params.get('bip_path') else _node(params.get('root','Bip001'))
    if source is not None and bool(source.controller.figureMode):
        raise ValueError('Exit source Biped Figure Mode before capturing animation')
    path=Path(params['bip_path']).resolve() if params.get('bip_path') else None
    if path and (path.suffix.lower()!='.bip' or not path.is_file()):
        raise ValueError('BIP file not found: '+str(path))
    old_time=rt.sliderTime;old_range=rt.animationRange;old_selection=list(rt.selection)
    root=None;created=[]
    try:
        with tempfile.TemporaryDirectory(prefix='maya_bip_') as directory:
            if path is None:
                path=Path(directory)/'source.bip'
                rt.biped.saveBipFile(source.controller,str(path))
            # Dimensions are internal numeric units. The captured profile is in
            # Maya centimetres; explicit calibration avoids changing Max units.
            height=max(p[2] for p in points.values())-min(p[2] for p in points.values())+10
            root=rt.biped.createNew(height,0,rt.Point3(0,0,0),spineLinks=3,
                                    neckLinks=1,arms=True,fingers=5,fingerLinks=3,toes=1,toeLinks=1)
            def descendants(n):
                yield n
                for child in n.children:yield from descendants(child)
            created=list(descendants(root))
            root.controller.rootName='MayaBipTransfer_'+uuid.uuid4().hex[:10]
            name=str(root.name)
            rt.hide(rt.Array(*created))
            root.controller.figureMode=True
            rt.biped.setTransform(root,rt.Name('rotation'),rt.quat(90,rt.Point3(0,0,1)),False)
            def node(label):return _node(name+' '+label)
            def length(a,b):return math.dist(points[a],points[b])
            def distance(a,b):return float(rt.distance(node(a).transform.row4,node(b).transform.row4))
            # Biped pelvis local X controls spine height; Z controls hip width.
            pelvis=node('Pelvis');s=rt.biped.getTransform(pelvis,rt.Name('scale'))
            rt.biped.setTransform(pelvis,rt.Name('scale'),rt.Point3(
                s.x*length('Pelvis','Spine')/distance('Pelvis','Spine'),s.y,
                s.z*length('L Thigh','R Thigh')/distance('L Thigh','R Thigh')),False)
            for a,b in PAIRS[1:]:
                n=node(a);s=rt.biped.getTransform(n,rt.Name('scale'))
                rt.biped.setTransform(n,rt.Name('scale'),s*(length(a,b)/distance(a,b)),False)
            neck=node('Neck');s=rt.biped.getTransform(neck,rt.Name('scale'))
            rt.biped.setTransform(neck,rt.Name('scale'),rt.Point3(s.x,s.y,
                s.z*length('L Clavicle','R Clavicle')/distance('L Clavicle','R Clavicle')),False)
            rt.biped.setTransform(root,rt.Name('pos'),rt.Point3(*points['Pelvis']),False)
            # A uniform Foot scale matches ankle-to-ball length but changes the
            # sole pitch when the model has a different ankle height. Biped's
            # Foot X is vertical and Y is forward in this neutral Figure pose.
            # Fit those dimensions independently, keeping its native flat sole.
            foot_errors={}
            for side in ('L','R'):
                foot,toe=side+' Foot',side+' Toe0'
                wanted=rt.Point3(*points[toe])-rt.Point3(*points[foot])
                actual=node(toe).transform.row4-node(foot).transform.row4
                height=-float(wanted.z)
                reach=math.hypot(float(wanted.x),float(wanted.y))
                if height < -1e-5 or reach<=1e-5:
                    raise ValueError('脚部参考姿态无法确定平放脚掌，请用创建绑定时的姿态重新校准：'+foot)
                height=max(height,1e-5)
                s=rt.biped.getTransform(node(foot),rt.Name('scale'))
                rt.biped.setTransform(node(foot),rt.Name('scale'),rt.Point3(
                    s.x*height/abs(float(actual.z)),
                    s.y*reach/math.hypot(float(actual.x),float(actual.y)),s.z),False)
                actual=node(toe).transform.row4-node(foot).transform.row4
                foot_errors[foot]=max(abs(float(actual.z)+height),
                    abs(math.hypot(float(actual.x),float(actual.y))-reach))
            # Clavicle attachment height/depth is independent of clavicle
            # length. Preserve the model's neck-to-clavicle placement instead
            # of using the default Biped shoulder socket.
            neck_position=node('Neck').transform.row4
            socket_errors={}
            for side in ('L','R'):
                label=side+' Clavicle'
                delta=rt.Point3(*points[label])-rt.Point3(*points['Neck'])
                rt.biped.setTransform(node(label),rt.Name('pos'),neck_position+delta,False)
                socket_errors[label]=float(rt.distance(node(label).transform.row4,neck_position+delta))
            errors={a+' > '+b:abs(length(a,b)-distance(a,b)) for a,b in PAIRS}
            if max(list(errors.values())+list(foot_errors.values())+list(socket_errors.values()))>.002:
                raise RuntimeError('Native Biped Figure fitting failed: '+str(dict(lengths=errors,feet=foot_errors,shoulders=socket_errors)))
            root.controller.figureMode=False
            # Default native load retains the receiving Biped structure and
            # adapts the clip; never load onto the user's original Biped.
            rt.biped.loadBipFile(root.controller,str(path))
            if int(root.controller.spineLinks)!=3 or int(root.controller.neckLinks)!=1:
                raise ValueError('BIP changed the receiving skeleton structure')
            clip_range=rt.biped.getCurrentRange(root.controller)
            default_range=old_range if source is not None else clip_range
            start=float(params['start']) if params.get('start') is not None else float(default_range.start)
            end=float(params['end']) if params.get('end') is not None else float(default_range.end)
            labels=sorted({n for pair in PAIRS for n in pair})
            bones=[name+' '+label for label in labels]
            from .biped_keys import collect
            keys=collect(root,[_node(n) for n in bones])
            # COM is a distinct animated transform, not interchangeable with
            # Pelvis. Include its actual world matrix in every interchange.
            bones=[name]+bones
            data=_samples(name,start,end,float(params.get('step',.5)),bones,keys['times'])
            try:
                root.controller.figureMode=True
                data['reference']=_samples(name,start,start,1,bones)['samples'][0]['bones']
            finally:root.controller.figureMode=False
            # A stable interchange name survives deletion of the helper rig.
            public='MayaBiped'
            def rename(n):return public+n[len(name):] if n and n.startswith(name) else n
            for sample in data['samples']:
                sample['bones']={rename(k):v for k,v in sample['bones'].items()}
            data['reference']={rename(k):v for k,v in data['reference'].items()}
            data['parents']={rename(k):rename(v) for k,v in data['parents'].items()}
            data['source_keys']=dict(keys,tracks={rename(k):v for k,v in keys['tracks'].items()})
            data.update(root=public,format='max_biped_motion_v1',native_retarget={
                'version':3,'profile':params['profile'],'max_length_error':max(errors.values()),
                'hips_source':'com',
                'max_foot_dimension_error':max(foot_errors.values()),
                'max_shoulder_socket_error':max(socket_errors.values()),
                'reference_alignment':'anatomical_frames_and_sole',
                'source':'current_biped' if source is not None else str(path),
                'clip_range':[float(clip_range.start),float(clip_range.end)],
                'trajectory':'native_biped_world','center_start':True})
            return data
    finally:
        if root is not None and rt.isValidNode(root):
            # Delete only this operation's exact hierarchy, never by name glob.
            rt.delete(rt.Array(*[n for n in created if rt.isValidNode(n)]))
        rt.animationRange=old_range;rt.sliderTime=old_time
        rt.select(rt.Array(*[n for n in old_selection if rt.isValidNode(n)])) if old_selection else rt.clearSelection()
