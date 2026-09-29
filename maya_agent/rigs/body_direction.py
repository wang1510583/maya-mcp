"""Two acyclic body translation solves sharing the existing animator controls."""
import json

VERSION='1.1.0'


def _data(control):
    import maya.cmds as c
    return json.loads(c.getAttr(control+'.bodyDriveData'))


def enable(rig):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import arm_ik,live_edit
    controls=list(rig['controls'].values());hips=rig['controls']['hips'];chest=rig['controls']['chest']
    if c.objExists(hips+'.bodyDriveData'):
        from .body_direction_match import install
        return install(hips,_data(hips))
    zeros=[n[:-5]+'_zero' for n in controls];ns=rig['namespace']
    parent=c.listRelatives(zeros[0],p=True,fullPath=True) or []
    if any((c.listRelatives(z,p=True,fullPath=True) or [])!=parent for z in zeros):raise ValueError('身体控制器基准组不在同一空间。')
    baseline={n:c.xform(n,q=True,ws=True,m=True) for n in rig['joints']+controls}
    created=[];replaced=[];auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    c.undoInfo(openChunk=True,chunkName='EnableBodyDirection');c.autoKeyframe(state=False);arm_ik._busy=True
    def node(kind,label):
        n=c.createNode(kind,name=ns+':bodyDrive_'+label,skipSelect=True);created.append(n);return n
    def edge(src,dst):c.connectAttr(src,dst,force=True)
    def replace(src,dst):
        old=c.connectionInfo(dst,sfd=True);replaced.append((old,dst,c.getAttr(dst)))
        edge(src,dst)
    def matrix_node(label,m):
        n=node('holdMatrix',label);c.setAttr(n+'.inMatrix',*list(m),type='matrix');return n+'.outMatrix'
    def choose(dst,back,label):
        source=c.connectionInfo(dst,sfd=True);value=c.getAttr(dst)[0]
        q=node('choice',label);edge(hips+'.bodyDrive',q+'.selector')
        if source:edge(source,q+'.input[0]')
        else:
            v=node('plusMinusAverage',label+'Rest');c.setAttr(v+'.input3D[0]',*value,type='double3');edge(v+'.output3D',q+'.input[0]')
        edge(back,q+'.input[1]');replace(q+'.output',dst)
    try:
        c.addAttr(hips,ln='bodyDrive',nn='身体驱动',at='enum',en='腰部驱动:胸部驱动',keyable=True)
        mode_off=node('reverse','forwardMode');edge(hips+'.bodyDrive',mode_off+'.inputX')
        # Keep the original hips world input independent of the switched zero.
        ref=node('transform','hipsReference')
        if parent:c.parent(ref,parent[0],relative=True)
        c.xform(ref,m=c.xform(zeros[0],q=True,m=True));c.setAttr(ref+'.visibility',False)
        c.setAttr(ref+'.offsetParentMatrix',*c.getAttr(zeros[0]+'.offsetParentMatrix'),type='matrix')
        virtual=node('multMatrix','forwardHips');edge(hips+'.matrix',virtual+'.matrixIn[0]');edge(hips+'.offsetParentMatrix',virtual+'.matrixIn[1]');edge(ref+'.worldMatrix[0]',virtual+'.matrixIn[2]')
        forwards=[];rotations=[]
        for i,z in enumerate(zeros):
            r=om.MTransformationMatrix(om.MMatrix(c.getAttr(z+'.matrix'))).rotation(asQuaternion=True).asMatrix()
            rotations.append(r)
            if i:
                decomp=c.connectionInfo(z+'.translate',sfd=True).split('.')[0]
                position=c.connectionInfo(decomp+'.inputMatrix',sfd=True).split('.')[0]
                forwards.append(position)
        first=forwards[0]+'.matrixIn[1]';source=c.connectionInfo(first,sfd=True)
        if source==hips+'.worldMatrix[0]':replace(virtual+'.matrixSum',first)
        elif source and c.nodeType(source.split('.')[0])=='multMatrix':
            assembly=source.split('.')[0]
            inputs=c.listConnections(assembly,s=True,d=False,p=True,c=True) or []
            matches=[dst for dst,src in zip(inputs[::2],inputs[1::2]) if src.split('[',1)[0]==hips+'.worldMatrix']
            if not matches:raise ValueError('未识别身体的正向空间输入。')
            for dst in matches:replace(virtual+'.matrixSum',dst)
        elif source!=hips+'.matrix':raise ValueError('未识别身体的正向矩阵输入：'+str(source))
        # In reverse mode the chest is the master; its old hips-follow space
        # is bypassed, otherwise that option would restore the old dependency.
        if c.objExists(chest+'.global'):
            pairs=c.listConnections(chest+'.global',s=False,d=True,p=True,c=True) or []
            effective=node('multDoubleLinear','chestSpace');edge(chest+'.global',effective+'.input1');edge(mode_off+'.outputX',effective+'.input2')
            for src,dst in zip(pairs[::2],pairs[1::2]):
                if c.nodeType(dst.split('.')[0]) in ('reverse','parentConstraint'):replace(effective+'.output',dst)
        # The reverse recursion reads local matrices only, never switched world
        # matrices. The two solves therefore cannot form a dependency cycle.
        top=node('composeMatrix','chestAnchor');c.setAttr(top+'.inputTranslate',*c.getAttr(zeros[-1]+'.translate')[0],type='double3')
        base=top+'.outputMatrix';backs={zeros[-1]:top+'.inputTranslate'}
        for i in range(len(controls)-2,-1,-1):
            j=i+1;offset=om.MVector(*list(om.MMatrix(c.getAttr(forwards[i]+'.matrixIn[0]')))[12:15])
            offset=(-offset)*rotations[i]*rotations[j].inverse()
            local=node('composeMatrix','reverseOffset'+str(i));c.setAttr(local+'.inputTranslate',*offset,type='double3')
            m=node('multMatrix','reversePosition'+str(i));edge(local+'.outputMatrix',m+'.matrixIn[0]');edge(controls[j]+'.matrix',m+'.matrixIn[1]')
            slot=2
            if j<len(controls)-1:
                connect=c.listRelatives(controls[j],p=True)[0]
                edge(connect+'.matrix',m+'.matrixIn[%d]'%slot);slot+=1
            edge(matrix_node('restRotation'+str(i),rotations[j]),m+'.matrixIn[%d]'%slot);edge(base,m+'.matrixIn[%d]'%(slot+1))
            d=node('decomposeMatrix','reverseTranslate'+str(i));edge(m+'.matrixSum',d+'.inputMatrix');backs[zeros[i]]=d+'.outputTranslate'
            pick=node('pickMatrix','reverseBase'+str(i));edge(m+'.matrixSum',pick+'.inputMatrix')
            for a in ('useRotate','useScale','useShear'):c.setAttr(pick+'.'+a,False)
            base=pick+'.outputMatrix'
        for i in range(1,len(controls)-1):
            connect=c.listRelatives(controls[i],p=True)[0];driven=c.listRelatives(connect,p=True)[0]
            original=c.connectionInfo(driven+'.translate',sfd=True)
            fraction=c.getAttr(original.split('.')[0]+'.input2X')
            frame=node('vectorProduct','hipsSlideFrame'+str(i));c.setAttr(frame+'.operation',3);c.setAttr(frame+'.matrix',*list(rotations[0]*rotations[i].inverse()),type='matrix');edge(hips+'.translate',frame+'.input1')
            slide=node('multiplyDivide','hipsSlide'+str(i));edge(frame+'.output',slide+'.input1');c.setAttr(slide+'.input2',*[1-fraction]*3,type='double3')
            choose(driven+'.translate',slide+'.output','slideChoice'+str(i))
        for i,z in enumerate(zeros):choose(z+'.translate',backs[z],'positionChoice'+str(i))
        error=max(abs(a-b) for n,m in baseline.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        if error>1e-5:raise RuntimeError('安装身体驱动改变了姿态：'+str(error))
        data=dict(version=VERSION,root=rig.get('root',zeros[0]),global_plug=hips+'.bodyDrive',controls=controls,joints=rig['joints'],created=created)
        c.addAttr(hips,ln='bodyDriveData',dt='string');c.setAttr(hips+'.bodyDriveData',json.dumps(data),type='string',lock=True)
        from .body_direction_match import install
        data=install(hips,data)
        rig['body_drive']=data;rig.setdefault('nodes',[]).extend(data['created'])
        return data
    except Exception:
        for old,dst,value in reversed(replaced):
            current=c.connectionInfo(dst,sfd=True)
            if current:c.disconnectAttr(current,dst)
            if old:edge(old,dst)
            elif isinstance(value,list):c.setAttr(dst,*value[0],type='double3')
            else:c.setAttr(dst,value)
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        if c.objExists(hips+'.bodyDrive'):c.deleteAttr(hips+'.bodyDrive')
        raise
    finally:
        arm_ik._busy=busy;c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True);arm_ik.install()


def _linear_solve(a,b):
    n=len(b);rows=[list(row)+[v] for row,v in zip(a,b)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda i:abs(rows[i][col]))
        if abs(rows[pivot][col])<1e-10:raise RuntimeError('身体姿态补偿矩阵不可解。')
        rows[col],rows[pivot]=rows[pivot],rows[col];v=rows[col][col]
        rows[col]=[x/v for x in rows[col]]
        for i in range(n):
            if i==col:continue
            v=rows[i][col]
            if abs(v)>1e-14:rows[i]=[x-v*y for x,y in zip(rows[i],rows[col])]
    return [row[-1] for row in rows]


def switch(control,value,key=None,previous=None):
    from .body_direction_match import switch as match
    return match(control,value,key=key,previous=previous)


def enable_character(root):
    import maya.cmds as c
    rig=json.loads(c.getAttr(root+'.integratedRigData'));data=enable(rig['parts']['body'])
    c.setAttr(root+'.integratedRigData',lock=False);c.setAttr(root+'.integratedRigData',json.dumps(rig,ensure_ascii=False),type='string',lock=True)
    return data
