"""Discrete body-space compensation, separate from animator TR interpolation.

Offsets live on the original controls. Each mode has its own stepped samples;
before its first sample it is identically zero, without a preceding-frame key.
"""
import json
import math

POSITION_TOLERANCE_CM = 0.02
BASIS_TOLERANCE = 1e-5


def _check_pose(baseline, current, cm_per_unit=1.0):
    """Separate world distance from rotation/scale matrix tolerances."""
    position=basis=overall=0.0
    for n,before in baseline.items():
        delta=[abs(a-b) for a,b in zip(before,current[n])]
        if not all(math.isfinite(v) for v in delta):
            raise RuntimeError('身体驱动姿态校验出现无效数值，已回退。')
        position=max(position,math.sqrt(sum(v*v for v in delta[12:15]))*cm_per_unit)
        basis=max(basis,max(delta[:12]))
        overall=max(overall,max(delta))
    if position>POSITION_TOLERANCE_CM or basis>BASIS_TOLERANCE:
        raise RuntimeError('身体驱动切换未保留姿态，已回退：位置误差 %.9g 厘米（允许 %.9g），旋转/缩放矩阵误差 %.9g（允许 %.9g）'
                           %(position,POSITION_TOLERANCE_CM,basis,BASIS_TOLERANCE))
    return overall


def install(control, data):
    import maya.cmds as c
    from . import live_edit
    if data.get('match_inputs'):return data
    ns=control.rsplit(':',1)[0];created=[];inputs={};parents={};rewired=[];added=[]
    baseline={n:c.xform(n,q=True,ws=True,m=True) for n in data['controls']+data['joints']}
    def node(kind,label):
        n=c.createNode(kind,name=ns+':bodyMatch_'+label,skipSelect=True);created.append(n);return n
    def edge(src,dst):c.connectAttr(src,dst,force=True)
    try:
        starts=[]
        for mode in (0,1):
            p=control+'.bodyMatchStart'+str(mode)
            c.addAttr(control,ln=p.split('.')[-1],at='double',dv=-1e12,hidden=True);added.append(p);starts.append(p)
        for i,n in enumerate(data['controls']):
            # Capture original consumers before introducing our own matrix inputs.
            pairs=c.listConnections(n,s=False,d=True,p=True,c=True) or []
            parent=c.listRelatives(n,p=True,fullPath=True)[0];parents[n]=parent
            comp=node('transform','space'+str(i));c.parent(comp,parent,relative=True)
            inp=node('decomposeMatrix','input'+str(i));edge(n+'.rotateOrder',inp+'.inputRotateOrder')
            inputs[n]=dict(input=inp,space=comp,parent=parent,offsets={})
            gates=[]
            for mode in (0,1):
                gate=node('condition','timeGate'+str(i)+'_'+str(mode));gates.append(gate)
                c.setAttr(gate+'.operation',3);edge('time1.outTime',gate+'.firstTerm');edge(starts[mode],gate+'.secondTerm')
                c.setAttr(gate+'.colorIfTrueR',1);c.setAttr(gate+'.colorIfFalseR',0)
            for channel in ('translate','rotate'):
                for mode in (0,1):inputs[n]['offsets'][str(mode)+channel]=[]
                for axis in 'XYZ':
                    choose=node('choice',channel+axis+'Mode'+str(i));edge(data['global_plug'],choose+'.selector')
                    for mode in (0,1):
                        p=n+'.bodyMatch'+str(mode)+channel.title()+axis
                        c.addAttr(n,ln=p.split('.')[-1],at='double',hidden=True);added.append(p)
                        inputs[n]['offsets'][str(mode)+channel].append(p)
                        gate=node('multDoubleLinear',channel+axis+'Gate'+str(i)+'_'+str(mode))
                        edge(p,gate+'.input1');edge(gates[mode]+'.outColorR',gate+'.input2')
                        edge(gate+'.output',choose+'.input[%d]'%mode)
                    output=choose+'.output'
                    if channel=='rotate':
                        unit=node('unitConversion','radians'+axis+str(i));c.setAttr(unit+'.conversionFactor',math.pi/180)
                        edge(output,unit+'.input');output=unit+'.output'
                    edge(output,comp+'.'+channel+axis)
            edge(n+'.rotateOrder',comp+'.rotateOrder')
            # Constant parent offsets retain Maya's native manipulator axes.
            # Feed effective local values only into the original body math.
            inv=node('inverseMatrix','opmInverse'+str(i));edge(n+'.offsetParentMatrix',inv+'.inputMatrix')
            m=node('multMatrix','effective'+str(i))
            for k,p in enumerate((n+'.matrix',n+'.offsetParentMatrix',comp+'.matrix',inv+'.outputMatrix')):edge(p,m+'.matrixIn[%d]'%k)
            edge(m+'.matrixSum',inp+'.inputMatrix');c.parent(n,comp,relative=True)
            for src,dst in zip(pairs[::2],pairs[1::2]):
                attr=src.split('.',1)[1];kind=c.nodeType(dst.split('.')[0])
                # Constraints already consume the compensated parentMatrix.
                # Only the body's local input math needs the effective channels.
                if kind.endswith('Constraint') and kind!='orientConstraint':continue
                if not dst.startswith(ns+':'):continue
                if attr in ('matrix','translate','rotate') or attr in live_edit.TR:
                    replacement=m+'.matrixSum' if attr=='matrix' else inp+'.output'+attr[0].upper()+attr[1:]
                    edge(replacement,dst);rewired.append((src,dst))
        delta=max(abs(x-y) for n,m in baseline.items() for x,y in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if delta>1e-5:raise RuntimeError('安装身体切换补偿改变了姿态：'+str(delta))
        data.update(match_inputs=inputs,version='1.1.0');data['created'].extend(created)
        c.setAttr(control+'.bodyDriveData',lock=False);c.setAttr(control+'.bodyDriveData',json.dumps(data),type='string',lock=True)
        return data
    except Exception:
        for src,dst in reversed(rewired):edge(src,dst)
        for n,parent in parents.items():
            if c.objExists(n):c.parent(n,parent,relative=True)
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        for p in reversed(added):
            if c.objExists(p):c.deleteAttr(p)
        raise


def switch(control,value,key=None,previous=None,mode_plug=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import body_direction,arm_ik,live_edit,live_layers
    if value not in (0,1):raise ValueError('身体驱动仅支持 0 或 1。')
    data=body_direction._data(control);plug=mode_plug or data['global_plug'];old=c.getAttr(plug) if previous is None else previous
    if data.get('fixed_zero'):
        from .body_zero import switch as match_zero
        return match_zero(control,value,key=key,previous=previous,mode_plug=mode_plug)
    if old==value:return dict(changed=False)
    auto=c.autoKeyframe(q=True,state=True);key=auto if key is None else key;busy=arm_ik._busy;arm_ik._busy=True
    c.undoInfo(openChunk=True,chunkName='MatchBodyDirection');c.autoKeyframe(state=False);snapshot=None
    try:
        if c.getAttr(plug)!=old:c.setAttr(plug,old)
        data=install(control,data);controls=data['controls'];entries=data['match_inputs']
        frames={n:live_edit._frame(n) for n in controls}
        baseline={n:c.xform(n,q=True,ws=True,m=True) for n in data['joints']}
        from .zero_channels import resolve
        raw=list(dict.fromkeys([plug,data['global_plug']]+([data['chest_global']] if data.get('chest_global') else [])))+[resolve(n+'.'+a) for n in controls for a in live_edit.TR]
        body_mode=value if plug==data['global_plug'] else int(c.getAttr(data['global_plug']))
        chest_mode=(value if plug==data.get('chest_global') else int(c.getAttr(data['chest_global']))) if data.get('chest_global') else 0
        state=body_mode+2*chest_mode
        offsets=[p for n in controls for channel in ('translate','rotate') for p in entries[n]['offsets'][str(state)+channel]]
        start=control+'.bodyMatchStart'+str(state)
        fences=[];live_edit._fence('before',fences);snapshot=live_edit._snapshot(raw+offsets+[start]);fences.append(snapshot)
        first=not any(c.connectionInfo(p,sfd=True) for p in offsets)
        if key and first:c.setAttr(start,c.currentTime(q=True))
        elif key:c.setAttr(start,min(c.getAttr(start),c.currentTime(q=True)))
        elif first:c.setAttr(start,-1e12)
        c.setAttr(plug,value)
        endpoints=[controls[0],controls[-1]] if not body_mode else [controls[-1],controls[0]]
        for n in endpoints+controls[1:-1]:
            e=entries[n]
            raw_matrix=om.MMatrix(c.getAttr(n+'.matrix'))*om.MMatrix(c.getAttr(n+'.offsetParentMatrix'))
            pivot=om.MTransformationMatrix();pivot.setTranslation(om.MVector(c.getAttr(n+'.rotatePivot')[0]),om.MSpace.kTransform)
            desired=raw_matrix.inverse()*pivot.asMatrix().inverse()*frames[n]
            parent=om.MMatrix(c.xform(e['parent'],q=True,ws=True,m=True))
            euler=om.MTransformationMatrix(desired*parent.inverse()).rotation(asQuaternion=True).asEulerRotation()
            order=c.getAttr(n+'.rotateOrder');euler.reorderIt(order)
            euler=euler.closestSolution(om.MEulerRotation(*[math.radians(c.getAttr(p)) for p in e['offsets'][str(state)+'rotate']],order))
            for p,v in zip(e['offsets'][str(state)+'rotate'],euler):c.setAttr(p,math.degrees(v))
        translation=[p for n in controls for p in entries[n]['offsets'][str(state)+'translate']]
        for p in translation:c.setAttr(p,0)
        def positions():return [x for n in controls for x in list(live_edit._frame(n))[12:15]]
        base=positions();columns=[]
        for p in translation:
            c.setAttr(p,1);columns.append([x-y for x,y in zip(positions(),base)]);c.setAttr(p,0)
        wanted=[x for n in controls for x in list(frames[n])[12:15]]
        jacobian=list(zip(*columns))
        solved=body_direction._linear_solve(jacobian,[x-y for x,y in zip(wanted,base)])
        for p,v in zip(translation,solved):c.setAttr(p,v)
        # Body graphs include float-valued multiplyDivide/plusMinusAverage
        # nodes. Unit probes accumulate rounding when solving large offsets.
        # Still minimize error even when the final position tolerance permits it.
        for _ in range(4):
            residual=[x-y for x,y in zip(wanted,positions())]
            if max(abs(v) for v in residual)<1e-7:break
            correction=body_direction._linear_solve(jacobian,residual)
            for p,v in zip(translation,correction):c.setAttr(p,c.getAttr(p)+v)
        cm_per_unit=om.MDistance(1.0,om.MDistance.uiUnit()).asCentimeters()
        def error():
            return _check_pose(baseline,{n:c.xform(n,q=True,ws=True,m=True) for n in baseline},cm_per_unit)
        delta=error()
        if key:
            final={p:c.getAttr(p) for p in offsets}
            # Matching is structural, not additive animation. Keep it outside
            # the animator's layer stack, with stepped samples on the controls.
            for p,v in final.items():
                c.setKeyframe(p,v=v);c.keyTangent(p,e=True,ott='step')
            raw_snapshot=({p:snapshot[0][p] for p in raw},snapshot[1])
            live_layers.key_mode_switch(raw_snapshot,plug,force_plugs=raw)
            for p,v in final.items():c.setAttr(p,v)
        delta=error()
        live_edit._fence('after',[live_edit._snapshot(snapshot[0])])
        return dict(changed=True,mode=value,max_pose_error=delta)
    except Exception:
        if snapshot:
            # A failed key/layer commit may have introduced first-time curves.
            # Remove those before restoring the original values and tangents.
            registered=live_layers.blend_nodes();new_curves=set()
            for p in snapshot[0]:
                new_curves.update(live_layers.curves_for_plug(p,registered)-set(snapshot[1]))
            if new_curves:c.delete(list(new_curves))
            live_edit._restore(snapshot)
        raise
    finally:
        c.autoKeyframe(state=auto);arm_ik._busy=busy;c.undoInfo(closeChunk=True);arm_ik._sync_mode_cache()
