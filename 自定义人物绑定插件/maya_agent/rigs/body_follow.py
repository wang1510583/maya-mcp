"""Include inherited hips rotation in the spine's chest endpoint blend."""
import json


def enable(rig):
    import maya.cmds as c
    ns=rig['namespace'];hips=rig['controls']['hips'];chest=rig['controls']['chest']
    if not c.objExists(chest+'.global'):return None
    if c.objExists(chest+'.bodyFollowData'):return json.loads(c.getAttr(chest+'.bodyFollowData'))
    mids=[n for role,n in rig['controls'].items() if role not in ('hips','chest')]
    if not mids:return None
    created=[];replaced=[];slide_values={}
    def node(kind,label):
        n=c.createNode(kind,name=ns+':bodyFollow_'+label,skipSelect=True);created.append(n);return n
    def edge(src,dst):c.connectAttr(src,dst)
    # The fitting matrices already express endpoint rotations in each spine's
    # rest frame. Convert hips to chest rest axes, without reading world output
    # matrices (chest position itself depends on the intermediate spine chain).
    stem=mids[0][:-5]
    if not c.objExists(stem+'_hipsDelta'):return None
    import maya.api.OpenMaya as om
    mid_to_hips=om.MMatrix(c.getAttr(stem+'_hipsDelta.matrixIn[0]'))
    mid_to_chest=om.MMatrix(c.getAttr(stem+'_chestDelta.matrixIn[0]'))
    chest_to_hips=mid_to_chest.inverse()*mid_to_hips
    try:
        rotation=node('multMatrix','hipsInChest')
        c.setAttr(rotation+'.matrixIn[0]',*list(chest_to_hips),type='matrix')
        edge(ns+':hips_localRotation.outputMatrix',rotation+'.matrixIn[1]')
        c.setAttr(rotation+'.matrixIn[2]',*list(chest_to_hips.inverse()),type='matrix')
        blend=node('blendMatrix','inheritedRotation')
        edge(rotation+'.matrixSum',blend+'.target[0].targetMatrix')
        effective=ns+':bodyDrive_chestSpace.output'
        edge(effective if c.objExists(effective) else chest+'.global',blend+'.target[0].weight')
        output=node('multMatrix','chestRotation')
        edge(ns+':chest_localRotation.outputMatrix',output+'.matrixIn[0]')
        edge(blend+'.outputMatrix',output+'.matrixIn[1]')
        for control in mids:
            dst=control[:-5]+'_chestDelta.matrixIn[1]';old=c.connectionInfo(dst,sfd=True)
            replaced.append((old,dst));c.connectAttr(output+'.matrixSum',dst,force=True)
            # Chest stretching is distributed through local translation slides.
            # Those vectors must use the same inherited axes as the chest.
            slide=control[:-5]+'_slideFrame.matrix'
            slide_values[slide]=c.getAttr(slide)
            matrix=node('multMatrix',control.rsplit(':',1)[-1]+'_slide')
            c.setAttr(matrix+'.matrixIn[1]',*c.getAttr(slide),type='matrix')
            edge(blend+'.outputMatrix',matrix+'.matrixIn[0]');edge(matrix+'.matrixSum',slide)
        data=dict(version='1.0.0',created=created,replaced=replaced)
        c.addAttr(chest,ln='bodyFollowData',dt='string');c.setAttr(chest+'.bodyFollowData',json.dumps(data),type='string',lock=True)
        rig['body_follow']=data;rig.setdefault('nodes',[]).extend(created)
        return data
    except Exception:
        for src,dst in reversed(replaced):c.connectAttr(src,dst,force=True)
        for n in reversed(created):
            if c.objExists(n):c.delete(n)
        for plug,value in slide_values.items():c.setAttr(plug,*value,type='matrix')
        raise
