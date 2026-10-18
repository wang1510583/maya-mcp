"""Non-destructive regression on a user's rig: change temporary candidates only."""
import math,json
import maya.cmds as c
import maya.api.OpenMaya as om
from maya_agent.rigs.custom_body import continuous_rotation
from maya_agent.rigs.mobile_io import service

def verify(root):
    body=json.loads(c.getAttr(root+'.integratedRigData'))['parts']['body'];ns=body['namespace']
    before=service.module('export_snapshot')['fingerprint']();selection=c.ls(sl=True,long=True) or [];data=None;created=[]
    def make(kind):
        node=c.createNode(kind,name=ns+':rotationProbe',skipSelect=True);created.append(node);return node
    def copy(source,target):
        if not c.objExists(source) or not c.objExists(target):return
        value=c.getAttr(source);kind=c.getAttr(source,type=True)
        if value is None:return
        if kind=='matrix':c.setAttr(target,*value,type='matrix')
        elif kind in ('double3','float3'):c.setAttr(target,*value[0],type=kind)
        else:c.setAttr(target,value)
    def quat(plug,frame=None):
        v=c.getAttr(plug,**({} if frame is None else {'time':frame}))[0]
        return om.MEulerRotation(*[math.radians(x) for x in v]).asQuaternion()
    def angle(a,b):return math.degrees(2*math.acos(min(1.,abs((a*b.inverse()).w))))
    report={}
    try:
        data=continuous_rotation.candidate(body);row=data['outputs'][0];original=row['original'].split('.')[0]
        report['poseSamples']=193;report['maxPreservedDegrees']=max(angle(quat(row['original'],i*.25),quat(row['replacement'],i*.25)) for i in range(193))
        old=make('orientConstraint')
        for attr in ('offset','constraintParentInverseMatrix','constraintJointOrient','restRotate','enableRestPosition','interpType','constraintRotateOrder'):copy(original+'.'+attr,old+'.'+attr)
        for index in (0,1):
            for attr in ('targetRotate','targetRotateOrder','targetJointOrient','targetParentMatrix','targetWeight'):copy(original+'.target[%d].'%index+attr,old+'.target[%d].'%index+attr)
        sweeps=[]
        for index,role in enumerate(('hips','chest')):
            endpoint=next(n for n in data['created'] if n.rsplit(':',1)[-1]=='continuous_'+role)
            plug=endpoint+'.inputRotate';base=c.getAttr(plug)[0];source=c.connectionInfo(plug,sourceFromDestination=True);c.disconnectAttr(source,plug)
            compose=make('composeMatrix');c.connectAttr(plug,compose+'.inputRotate');c.connectAttr(endpoint+'.inputRotateOrder',compose+'.inputRotateOrder')
            mid=make('multMatrix');c.connectAttr(compose+'.outputMatrix',mid+'.matrixIn[0]')
            if role=='chest':copy(ns+':bodyFollow_chestRotation.matrixIn[1]',mid+'.matrixIn[1]')
            matrix=make('multMatrix');delta=body['controls'][row['role']][:-5]+'_'+role+'Delta'
            for k in (0,2):copy(delta+'.matrixIn[%d]'%k,matrix+'.matrixIn[%d]'%k)
            c.connectAttr(mid+'.matrixSum',matrix+'.matrixIn[1]');euler=make('decomposeMatrix');c.connectAttr(matrix+'.matrixSum',euler+'.inputMatrix');copy(delta+'Euler.inputRotateOrder',euler+'.inputRotateOrder')
            target=old+'.target[%d].targetRotate'%index;c.connectAttr(euler+'.outputRotate',target,force=True)
            for axis in range(3):
                previous=None;largest=0;boundary=0
                for step in range(721):
                    offset=-180+step*.5;values=list(base);values[axis]+=offset;c.setAttr(plug,*values,type='double3');current=quat(old+'.constraintRotate')
                    if previous is not None:
                        error=angle(previous,current)
                        if error>largest:largest=error;boundary=offset
                    previous=current
                previous=None;old_jump=new_step=0
                for step in range(201):
                    offset=boundary-.75+step*.005;values=list(base);values[axis]+=offset;c.setAttr(plug,*values,type='double3');current=(quat(old+'.constraintRotate'),quat(row['replacement']))
                    if previous:
                        old_jump=max(old_jump,angle(previous[0],current[0]));new_step=max(new_step,angle(previous[1],current[1]))
                    previous=current
                sweeps.append(dict(role=role,axis='XYZ'[axis],inputStep=.005,oldJump=old_jump,newMaxStep=new_step,offset=boundary))
                assert new_step<1.,sweeps[-1]
            c.setAttr(plug,*base,type='double3');c.connectAttr(source,plug,force=True);c.disconnectAttr(euler+'.outputRotate',target);copy(original+'.target[%d].targetRotate'%index,target)
        report['sweeps']=sweeps;assert report['maxPreservedDegrees']<1e-4,report
    finally:
        if created:c.delete(created)
        if data:c.delete(data['created'])
        c.select(selection,replace=True) if selection else c.select(clear=True)
        c.file(modified=before['modified']);after=service.module('export_snapshot')['fingerprint']();report['sceneUnchanged']=before==after
    assert report['sceneUnchanged'],report
    return report


def verify_control_chain(root):
    """Exercise cloned visible controls through the entire zero/matching input graph."""
    from maya_agent.rigs.custom_body.rotation_reference import Reference
    body=json.loads(c.getAttr(root+'.integratedRigData'))['parts']['body'];ns=body['namespace']
    before=service.module('export_snapshot')['fingerprint']();selection=c.ls(sl=True,long=True) or [];data=None;report={}
    try:
        data=continuous_rotation.candidate(body);probe=Reference(ns,data['created']);output=probe.source(data['outputs'][0]['replacement'])
        def editable(node,attr):
            # Resolve through the active candidate's copied input graph, keeping
            # its frozen animation correction separate from the editable copy.
            p=probe.source(node+'.'+attr);source=c.connectionInfo(p,sourceFromDestination=True)
            if source:c.disconnectAttr(source,p)
            if c.getAttr(p,lock=True):c.setAttr(p,lock=False)
            return p
        controls={role:probe.source(body['zero_controls'][role]+'.rotate') for role in ('hips','chest')}
        plugs={role:[editable(body['zero_controls'][role],'rotate'+axis) for axis in 'XYZ'] for role in controls}
        base={role:[c.getAttr(p) for p in plugs[role]] for role in plugs}
        global_plug=editable(body['controls']['chest'],'global');drive=editable(body['controls']['hips'],'bodyDrive')
        def q():return om.MEulerRotation(*[math.radians(v) for v in c.getAttr(output)[0]]).asQuaternion()
        def angle(a,b):return math.degrees(2*math.acos(min(1.,abs((a*b.inverse()).w))))
        rows=[]
        for drive_value,follow in ((0,0),(0,.5),(0,1),(1,0),(1,1)):
            c.setAttr(drive,drive_value);c.setAttr(global_plug,follow)
            for role in ('hips','chest'):
                for axis in range(3):
                    plug=plugs[role][axis];previous=None;largest=0;where=0
                    for i in range(721):
                        offset=-180+i*.5;c.setAttr(plug,base[role][axis]+offset);current=q()
                        if previous:
                            step=angle(previous,current)
                            if step>largest:largest=step;where=offset
                        previous=current
                    previous=None;fine=0
                    for i in range(201):
                        c.setAttr(plug,base[role][axis]+where-.75+i*.005);current=q()
                        if previous:fine=max(fine,angle(previous,current))
                        previous=current
                    rows.append(dict(drive=drive_value,follow=follow,role=role,axis='XYZ'[axis],maxHalfDegreeStep=largest,maxFineStep=fine))
                    c.setAttr(plug,base[role][axis]);assert fine<1,rows[-1]
        report=dict(control_chain_sweeps=rows,maxFineStep=max(r['maxFineStep'] for r in rows))
    finally:
        if data:c.delete(data['created'])
        c.select(selection,replace=True) if selection else c.select(clear=True)
        c.file(modified=before['modified']);report['sceneUnchanged']=before==service.module('export_snapshot')['fingerprint']()
    assert report['sceneUnchanged'],report
    return report
