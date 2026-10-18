"""Compile the supported rig's DG to a closed, offline operation graph.

Read-only. Unsupported dynamic nodes fail export rather than silently approximating.
Angles in the operation graph are radians, distances centimetres, matrices Maya row-major.
"""
import json, math, hashlib, runpy, sys
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om

IDENTITY=[1.,0,0,0,0,1.,0,0,0,0,1.,0,0,0,0,1.]

class Compiler:
    def __init__(self, snapshot):
        self.ops=[]; self.cache={}; self.active=[]; self.inputs={}; self.plugs={}; self.types={}
        for control in snapshot['controls']:
            node=c.ls(control.get('nodeId',control['id']),long=True)[0]
            for i,a in enumerate(['rotateX','rotateY','rotateZ','translateX','translateY','translateZ']):
                plugs=control.get('inputPlugs')
                if plugs is not None and not plugs[i]:continue
                p=self.plug(plugs[i] if plugs is not None else node+'.'+a)
                # Ordinary keyed TR is still an editable controller input. Capture
                # its sampled values separately; do not freeze the curve at export.
                source=p.source() if p.isDestination else None
                animated=False
                if source is not None:
                    animated=om.MFnDependencyNode(source.node()).typeName in ('animCurveTA','animCurveTL','animCurveTT','animCurveTU')
                if (not p.isDestination or animated) and not p.isLocked:
                    self.inputs[self.name(p)]=(control['id'],i)

    def name(self,p):
        fn=om.MFnDependencyNode(p.node())
        n=om.MFnDagNode(p.node()).fullPathName() if p.node().hasFn(om.MFn.kDagNode) else fn.name()
        return n+'.'+p.partialName(includeNonMandatoryIndices=True,includeInstancedIndices=True,useLongNames=True,useFullAttributePath=True)

    def plug(self,name):
        if isinstance(name,om.MPlug):return name
        if name not in self.plugs:
            s=om.MSelectionList();s.add(name)
            try:p=s.getPlug(0)
            except Exception:
                node,attr=name.split('.',1);sel=om.MSelectionList();sel.add(node)
                p=om.MFnDependencyNode(sel.getDependNode(0)).findPlug(attr,False)
            if p.isArray:p=p.elementByLogicalIndex(0)
            self.plugs[name]=p
        return self.plugs[name]

    def value(self,p):
        if p.isCompound:return [self.value(p.child(i))[0] for i in range(p.numChildren())]
        a=p.attribute()
        if a.hasFn(om.MFn.kMatrixAttribute):return list(om.MFnMatrixData(p.asMObject()).matrix())
        if a.hasFn(om.MFn.kTypedAttribute) or a.hasFn(om.MFn.kGenericAttribute):
            try:
                obj=p.asMObject()
                if obj.hasFn(om.MFn.kMatrixData):return list(om.MFnMatrixData(obj).matrix())
            except RuntimeError:
                # Maya's unconnected typed-matrix constraint inputs have a
                # null data object; their effective transform is identity.
                if a.hasFn(om.MFn.kTypedAttribute) and om.MFnTypedAttribute(a).attrType()==om.MFnData.kMatrix and c.getAttr(p.name()) is None:
                    return list(IDENTITY)
        if a.hasFn(om.MFn.kUnitAttribute):
            typ=om.MFnUnitAttribute(a).unitType()
            if typ==om.MFnUnitAttribute.kAngle:return [p.asMAngle().asRadians()]
            if typ==om.MFnUnitAttribute.kDistance:return [p.asMDistance().asCentimeters()]
        # Generic choice output can be matrix/vector/scalar.
        try:return [p.asDouble()]
        except Exception:
            v=c.getAttr(p.name())
            while isinstance(v,(list,tuple)) and len(v)==1:v=v[0]
            return list(v) if isinstance(v,(list,tuple)) else [v]

    def emit(self,kind,deps=(),data=None,truth=None,name=''):
        index=len(self.ops)
        static=kind!='input' and all(self.ops[d]['op']=='const' for d in deps)
        if truth is not None and static:kind='const';deps=();data=truth
        row={'op':kind,'args':list(deps)}
        if data is not None:row['data']=data
        if truth is not None:row['truth']=truth
        if name:row['name']=name
        self.ops.append(row);return index

    def const(self,v):return self.emit('const',data=v if isinstance(v,list) else [v])

    def get(self,name):
        p=self.plug(name);key=self.name(p)
        if key in self.cache:return self.cache[key]
        if key in self.active:raise RuntimeError('Dynamic cycle: '+' -> '.join(self.active[-12:]+[key]))
        self.active.append(key)
        try:
            if key in self.inputs:
                uid,axis=self.inputs[key]
                out=self.emit('input',data={'id':uid,'axis':axis,'base':self.value(p)[0]},truth=self.value(p),name=key)
            elif p.isDestination:out=self.get(p.sourceWithConversion())
            else:out=self.compile(p)
            self.cache[key]=out;return out
        finally:self.active.pop()

    def compile(self,p):
        name=self.name(p);node=name.split('.')[0];attr=name.split('.',1)[1]
        typ=om.MFnDependencyNode(p.node()).typeName
        def g(a):return self.get(node+'.'+a)
        def indices(a):return c.getAttr(node+'.'+a,multiIndices=True) or []
        def op(kind,attrs=(),data=None):return self.emit(kind,[g(a) for a in attrs],data,self.value(p),name)
        # Child plugs of computed compounds share the parent's operation.
        if p.isChild and not p.parent().isElement:
            parent=p.parent();at=parent.partialName(useLongNames=True)
            computed=(at.startswith(('output','outColor','constraintRotate','constraintTranslate')) or at=='outValue')
            if computed:
                i=next(i for i in range(parent.numChildren()) if parent.child(i)==p)
                return self.emit('component',[self.get(parent)],[i],self.value(p),name)

        if typ in ('transform','joint') and attr in ('worldMatrix[0]','worldInverseMatrix[0]','parentMatrix[0]','parentInverseMatrix[0]','matrix','inverseMatrix'):
            if attr in ('worldInverseMatrix[0]','parentInverseMatrix[0]','inverseMatrix'):
                return op('inverse',[{'worldInverseMatrix[0]':'worldMatrix[0]','parentInverseMatrix[0]':'parentMatrix[0]','inverseMatrix':'matrix'}[attr]])
            if attr=='parentMatrix[0]':
                parents=c.listRelatives(node,parent=True,fullPath=True) or []
                deps=[g('offsetParentMatrix')]
                if parents and c.getAttr(node+'.inheritsTransform'):deps.append(self.get(parents[0]+'.worldMatrix[0]'))
                return self.emit('matmul',deps,truth=self.value(p),name=name)
            if attr=='worldMatrix[0]':return op('matmul',['matrix','parentMatrix[0]'])
            attrs=['translate','rotate','scale','shear','rotateOrder','rotateAxis','rotatePivot','rotatePivotTranslate','scalePivot','scalePivotTranslate']
            if typ=='joint':attrs+=['jointOrient','inverseScale','segmentScaleCompensate']
            return op('transform',attrs,[typ=='joint'])
        if typ=='multMatrix' and attr=='matrixSum':return op('matmul',['matrixIn[%d]'%i for i in indices('matrixIn')])
        if typ=='inverseMatrix' and attr=='outputMatrix':return op('inverse',['inputMatrix'])
        if typ=='holdMatrix' and attr=='outMatrix':return op('copy',['inMatrix'])
        if typ=='composeMatrix' and attr=='outputMatrix':return op('compose',['inputTranslate','inputRotate','inputScale','inputShear','inputRotateOrder','inputQuat','useEulerRotation'])
        if typ=='decomposeMatrix' and attr.startswith('output'):return op('decompose',['inputMatrix','inputRotateOrder'],[attr])
        if typ=='pickMatrix' and attr=='outputMatrix':return op('pick',['inputMatrix','useTranslate','useRotate','useScale','useShear'])
        if typ=='choice' and attr=='output':
            sel=g('selector')
            if self.ops[sel]['op']=='const':return g('input[%d]'%int(self.ops[sel]['data'][0]))
            ii=indices('input');return self.emit('choice',[sel]+[g('input[%d]'%i) for i in ii],ii,self.value(p),name)
        if typ in ('addDoubleLinear','multDoubleLinear','unitConversion') and attr in ('output',):
            return op('add' if typ=='addDoubleLinear' else 'mul',['input','conversionFactor'] if typ=='unitConversion' else ['input1','input2'])
        if typ=='multiplyDivide' and attr=='output':return op('multiplyDivide',['input1','input2','operation'])
        if typ=='plusMinusAverage' and attr.startswith('output'):
            dim=attr[-2:];return op('plusMinusAverage',['operation']+['input%s[%d]'%(dim,i) for i in indices('input'+dim)])
        if typ=='reverse' and attr=='output':return op('reverse',['input'])
        if typ=='condition' and attr=='outColor':return op('condition',['firstTerm','secondTerm','operation','colorIfTrue','colorIfFalse'])
        if typ=='vectorProduct' and attr=='output':return op('vectorProduct',['input1','input2','matrix','operation','normalizeOutput'])
        if typ=='pointMatrixMult' and attr=='output':return op('pointMatrixMult',['inPoint','inMatrix','vectorMultiply'])
        if typ.startswith('animBlendNodeAdditive') and attr=='output':return op('animBlend',['inputA','inputB','weightA','weightB'])
        if typ=='eulerToQuat' and attr=='outputQuat':return op('eulerQuat',['inputRotate','inputRotateOrder'])
        if typ=='quatToEuler' and attr=='outputRotate':return op('quatEuler',['inputQuat','inputRotateOrder'])
        if typ in ('quatProd','quatAdd','quatSlerp') and attr=='outputQuat':return op(typ,['input1Quat','input2Quat']+(['inputT'] if typ=='quatSlerp' else []))
        if typ in ('quatNormalize','quatInvert','quatNegate','quatConjugate') and attr=='outputQuat':return op(typ,['inputQuat'])
        if typ=='expression' and attr.startswith('output['):
            expr=c.expression(node,q=True,s=True)
            # Only the registered soft-limb formula is supported, never execute MEL on device.
            if '$soft_knee_pivotY' not in expr or '$soft_scale_range' not in expr or len(indices('input'))!=8:raise ValueError('Unsupported expression '+node)
            return op('softLimb',['input[%d]'%i for i in range(8)],[int(attr.split('[')[1].split(']')[0])])
        if typ.endswith('Constraint') and attr in ('constraintTranslate','constraintRotate','constraintVector'):
            attrs=['constraintParentInverseMatrix']
            targets=indices('target')
            fields=['targetWeight','targetParentMatrix']
            if typ in ('pointConstraint','parentConstraint','aimConstraint'):fields+=['targetTranslate','targetRotatePivot','targetRotateTranslate']
            if typ in ('orientConstraint','parentConstraint'):fields+=['targetRotate','targetRotateOrder','targetJointOrient']
            if typ=='parentConstraint':fields+=['targetOffsetTranslate','targetOffsetRotate','targetScale','targetInverseScale','targetScaleCompensate']
            for i in targets:attrs+=['target[%d].%s'%(i,f) for f in fields]
            extra=[]
            if typ in ('pointConstraint','parentConstraint','aimConstraint'):extra+=['constraintRotatePivot','constraintRotateTranslate']
            if attr=='constraintRotate' or typ=='aimConstraint':extra+=['constraintRotateOrder','constraintJointOrient','restRotate']
            if typ in ('pointConstraint','orientConstraint','aimConstraint'):extra+=['offset']
            if typ in ('parentConstraint','orientConstraint'):extra+=['interpType']
            if typ=='pointConstraint':extra+=['constraintOffsetPolarity']
            if typ=='aimConstraint':extra+=['constraintTranslate','aimVector','upVector','worldUpVector','worldUpMatrix','worldUpType']
            return op(typ,attrs+extra,{'output':attr,'targets':len(targets),'fields':fields,'extra':extra})
        if typ=='blendMatrix' and attr=='outputMatrix':
            fields=['targetMatrix','useMatrix','weight','translateWeight','rotateWeight','scaleWeight','shearWeight']
            return op('blendMatrix',['inputMatrix','envelope']+['target[%d].%s'%(i,f) for i in indices('target') for f in fields])
        if p.isCompound:return self.emit('vector',[self.get(p.child(i)) for i in range(p.numChildren())],truth=self.value(p),name=name)
        # Undriven stored attributes and frozen source animation are constants.
        fn=om.MFnAttribute(p.attribute())
        if fn.writable or typ.startswith('animCurve') or typ in ('time','timeToUnitConversion'):return self.emit('const',data=self.value(p),truth=self.value(p),name=name)
        raise ValueError('Unsupported computed output: '+typ+' '+name)

def export(snapshot_path,destination):
    sys.setrecursionlimit(12000)
    snapshot_source=Path(snapshot_path);snap=json.loads(snapshot_source.read_text(encoding='utf8'))
    fingerprint=runpy.run_path(str(Path(__file__).with_name('export_snapshot.py')))['fingerprint']
    before=fingerprint();compiler=Compiler(snap)
    outputs={}
    for row in snap['controls']+snap['joints']:
        node=c.ls(row.get('nodeId',row['id']),long=True)[0]
        world=c.xform(node,q=True,ws=True,m=True)
        if max(abs(a-b) for a,b in zip(world,row['worldMatrix']))>1e-5:
            raise ValueError('Scene no longer matches the snapshot; export a new snapshot first: '+node)
        outputs[row['id']]=compiler.get(node+'.worldMatrix[0]')
    # Preserve the native FK gesture contract: align original inputs to solved
    # frames, edit the selected input, and validate the real solver joints.
    from maya_agent.rigs import zero_channels
    native_arm_gestures={}
    for part,part_data in snap['rigMetadata']['parts'].items():
        if part not in ('arm_L','arm_R'):continue
        root=part_data['root'];side=part[-1];ns=part_data['namespace']
        if not c.objExists(root+'.liveAlignmentData'):continue
        data=json.loads(c.getAttr(root+'.liveAlignmentData'))
        controls={row['role']:row for row in snap['controls'] if row['part']==part}
        # World IK uses separate custom channels; do not silently reinterpret it.
        wrist=c.ls(controls['end_fk']['id'],long=True)[0]
        if not snap.get('modePanel') and c.objExists(wrist+'.global') and c.getAttr(wrist+'.global')!=0:continue
        frames=[]
        for role in ('shoulder_fk','middle_fk','end_fk','pole_locator'):
            node=data['inputs'].get(role,ns+':elb_'+side+'1');row=controls[role]
            world=compiler.get(node+'.worldMatrix[0]')
            mask=[False]*6
            for uid,axis in compiler.inputs.values():
                if uid==row['id']:mask[axis]=True
            frames.append(dict(id=row['id'],world=world,local=compiler.get(node+'.matrix'),
                parent=compiler.get(node+'.parentMatrix[0]'),editable=mask,
                target=compiler.get(data['targets'].get(role,node)+'.worldMatrix[0]')))
        reset_row=controls['end_locator'];reset_node=c.ls(reset_row['id'],long=True)[0]
        source=ns+':hand_'+side+'1';reset=[]
        for attr in ('rotateX','rotateY','rotateZ','translateX','translateY','translateZ'):
            plug=zero_channels.resolve(source+'.'+attr)
            reset.append(-zero_channels.offset(plug)-c.getAttr(reset_node+'.'+attr))
        cfg=dict(frames=frames,resetId=reset_row['id'],reset=reset,
                 guards=[compiler.get(ns+':joint'+str(i)+'.worldMatrix[0]') for i in (1,2,3)])
        for role in ('shoulder_fk','middle_fk','end_fk'):native_arm_gestures[controls[role]['id']]=cfg
    native_control_gestures={}
    for row in snap['controls']:
        uid=row['id'];mask=[False]*6
        for rid,axis in compiler.inputs.values():
            if rid==uid:mask[axis]=True
        if not any(mask) or uid in native_arm_gestures or row.get('inputOnly'):continue
        node=c.ls(uid,long=True)[0]
        if row['part']=='character' or row['part'].startswith(('hand_','generic_')):
            native_control_gestures[uid]=dict(kind='direct',frame=dict(id=uid,world=compiler.get(node+'.worldMatrix[0]'),local=compiler.get(node+'.matrix'),parent=compiler.get(node+'.parentMatrix[0]'),editable=mask))
            continue
        if not c.objExists(node+'.zeroChannelData'):
            raise ValueError('Native editing requires registered zero-control metadata: '+node)
        data=json.loads(c.getAttr(node+'.zeroChannelData'))
        if data['part'].startswith('arm'):
            from maya_agent.rigs import arm_ik_shared
            if not snap.get('modePanel') and arm_ik_shared.active(data['root'],data['role']):
                raise ValueError('World IK custom-channel editing is not supported by this snapshot format: '+node)
        source=data['source']
        if c.objExists(source+'.liveInput'):source=(c.listConnections(source+'.liveInput',s=True,d=False) or [source])[0]
        frame=dict(id=uid,world=compiler.get(source+'.worldMatrix[0]'),local=compiler.get(source+'.matrix'),
                   parent=compiler.get(source+'.parentMatrix[0]'),editable=mask)
        native_control_gestures[uid]=dict(kind='zero',frame=frame,bodyRotation=data['part']=='body')
    mode_module=runpy.run_path(str(Path(__file__).with_name('export_modes.py')))
    modes,aliases=mode_module['compile_modes'](snap,compiler)
    skins={}
    for mesh in snap['meshes']:
        skin=mesh['skin']['name']
        source_method=method=c.getAttr(skin+'.skinningMethod')
        if method==2:
            import maya.api.OpenMayaAnim as oma
            selection=om.MSelectionList();selection.add(skin);fnskin=oma.MFnSkinCluster(selection.getDependNode(0))
            path=fnskin.getPathAtIndex(0);components=om.MFnSingleIndexedComponent();component=components.create(om.MFn.kMeshVertComponent)
            components.addElements(range(om.MFnMesh(path).numVertices))
            blend=list(fnskin.getBlendWeights(path,component))
            if c.listConnections(skin+'.blendWeights',s=True,d=False) or any(v!=0. for v in blend):
                raise ValueError('Unsupported nonzero or driven dual-quaternion blend weights: '+skin)
            method=0  # Blended skin with identically zero DQ weights is linear.
        if method not in (-1,0):raise ValueError('Unsupported skin method: '+skin)
        if c.getAttr(skin+'.envelope')!=1 or c.getAttr(skin+'.useComponents'):raise ValueError('Unsupported skin envelope or component mode: '+skin)
        p=compiler.plug(skin+'.input[0].inputGeometry');fn=om.MFnMesh(p.asMObject())
        geom=list(om.MFnMatrixData(compiler.plug(skin+'.geomMatrix').asMObject()).matrix())
        skins[mesh['id']]={'inputPositions':[[v.x,v.y,v.z] for v in fn.getPoints(om.MSpace.kObject)],'geomMatrix':geom,'method':method,'sourceMethod':source_method}
    result={'format':'maya-portable-graph','version':1,'sourceSnapshotSha256':hashlib.sha256(snapshot_source.read_bytes()).hexdigest(),
            'characterId':snap['characterId'],'rigVersion':snap['rigVersion'],'sourceFrame':snap['sourceFrame'],
            'ops':compiler.ops,'outputs':outputs,'nativeArmGestures':native_arm_gestures,'nativeArmGestureVersion':3,'nativeControlGestures':native_control_gestures,'skins':skins,'editableInputs':{k:list(v) for k,v in compiler.inputs.items()}}
    result['modePanel']=modes;result['ikAliases']=aliases
    metadata=runpy.run_path(str(Path(__file__).with_name('export_mesh_shading.py')))['mesh_metadata']
    shading={}
    for mesh in snap['meshes']:
        data=metadata(mesh)
        if data is not None:shading[mesh['id']]=data
    if shading:result['meshShading']={'format':'maya-mesh-shading','version':1,'sourceSnapshotSha256':result['sourceSnapshotSha256'],'meshes':shading}
    result['meshAppearance']=runpy.run_path(str(Path(__file__).with_name('export_mesh_appearance.py')))['appearance'](snap,result['sourceSnapshotSha256'])
    if fingerprint()!=before:raise RuntimeError('Scene changed during read-only compilation')
    Path(destination).write_text(json.dumps(result,separators=(',',':'),allow_nan=False),encoding='utf8')
    from collections import Counter
    return {'path':destination,'operations':len(compiler.ops),'types':dict(Counter(o['op'] for o in compiler.ops)), 'sceneUnchanged':True,'appearance':{'textures':len(result['meshAppearance']['images']),'warnings':result['meshAppearance']['warnings']}}

def compact(source,destination):
    """Remove dead branches, deduplicate constants and strip test truth values."""
    graph=json.loads(Path(source).read_text(encoding='utf8'));old=graph['ops'];ops=[];mapping={};constants={}
    def visit(i):
        if i in mapping:return mapping[i]
        row=old[i];args=[visit(j) for j in row['args']]
        key=json.dumps(row['data']) if row['op']=='const' else None
        if key is not None and key in constants:mapping[i]=constants[key];return mapping[i]
        new={k:v for k,v in row.items() if k!='truth'};new['args']=args
        mapping[i]=len(ops);ops.append(new)
        if key is not None:constants[key]=mapping[i]
        return mapping[i]
    graph['outputs']={uid:visit(i) for uid,i in graph['outputs'].items()}
    for cfg in graph.get('nativeArmGestures',{}).values():
        for frame in cfg['frames']:
            for key in ('world','local','parent','target'):frame[key]=visit(frame[key])
        cfg['guards']=[visit(i) for i in cfg['guards']]
    for cfg in graph.get('nativeControlGestures',{}).values():
        for key in ('world','local','parent'):cfg['frame'][key]=visit(cfg['frame'][key])
    runpy.run_path(str(Path(__file__).with_name('export_modes.py')))['remap_modes'](graph,visit)
    graph['ops']=ops
    Path(destination).write_text(json.dumps(graph,separators=(',',':'),allow_nan=False),encoding='utf8')
    return {'operations':len(ops),'path':str(destination)}

def package_snapshot(snapshot_path,graph_path,destination,animation_path=None):
    """A single transferable file, retaining exact snapshot bytes for animation identity."""
    target=Path(destination)
    if target.exists():raise FileExistsError(str(target))
    raw=Path(snapshot_path).read_bytes();graph=json.loads(Path(graph_path).read_text(encoding='utf8'))
    if graph['sourceSnapshotSha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('Solver snapshot mismatch')
    package={'format':'maya-mobile-project','schemaVersion':1,'snapshotJson':raw.decode('utf8'),'solver':graph}
    if animation_path:
        animation=json.loads(Path(animation_path).read_text(encoding='utf8'))
        if animation.get('sourceSnapshotSha256')!=graph['sourceSnapshotSha256'] or animation.get('characterId')!=graph['characterId']:
            raise ValueError('Animation snapshot mismatch')
        package['animation']=animation
    target.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(package,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')
    if len(encoded)>32*1024*1024:raise ValueError('Mobile project exceeds 32 MiB limit; reduce mesh/animation/texture size')
    target.write_bytes(encoded)
    return {'path':str(target),'sourceSnapshotSha256':graph['sourceSnapshotSha256'],'bytes':target.stat().st_size}
