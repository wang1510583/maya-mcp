"""One original wrist surface for both FK and IK, retaining both animation tracks."""
import json


def binary_global(root):
    """Replace this rig's wrist mode with a two-item enum, retaining its curves."""
    import maya.cmds as c
    from . import arm_ik
    d=arm_ik._data(root);plug=d['global_plug']
    if c.getAttr(plug,type=True)=='enum':return
    node,attr=plug.rsplit('.',1);value=int(c.getAttr(plug)>=.5)
    proxies=[n+'.global' for n in [d['fk_wrist']]+list(d['controls'].values()) if n+'.global'!=plug and c.objExists(n+'.global')]
    pairs=c.listConnections(plug,s=True,d=True,p=True,c=True) or []
    edges=[(a,b) if c.isConnected(a,b) else (b,a) for a,b in zip(pairs[::2],pairs[1::2])]
    busy=arm_ik._busy;arm_ik._busy=True
    try:
        for a,b in edges:c.disconnectAttr(a,b)
        for p in proxies:c.deleteAttr(p)
        c.deleteAttr(plug);c.addAttr(node,ln=attr,nn='global',at='enum',en='0:1',dv=value,keyable=True)
        for p in proxies:c.addAttr(p.rsplit('.',1)[0],ln='global',proxy=plug,keyable=True)
        for a,b in edges:
            if b not in proxies:c.connectAttr(a,b,force=True)
        c.setAttr(plug,value)
    finally:arm_ik._busy=busy


def enable(root):
    import maya.cmds as c
    from . import arm_ik
    data=arm_ik._data(root)
    binary_global(root)
    if data.get('shared_wrist'):return data['shared_wrist']
    ctrl=data['fk_wrist'];driver=data['controls']['wrist'];ns=data['namespace'];created=[]
    def create(kind,label):
        n=c.createNode(kind,name=ns+':sharedWrist_'+label,skipSelect=True);created.append(n);return n
    old=c.connectionInfo(ctrl+'.offsetParentMatrix',sfd=True)
    original=c.getAttr(ctrl+'.offsetParentMatrix')
    follow=create('multMatrix','follow')
    c.connectAttr(ctrl+'.inverseMatrix',follow+'.matrixIn[0]')
    c.connectAttr(driver+'.worldMatrix[0]',follow+'.matrixIn[1]')
    parent=(c.listRelatives(ctrl,p=True,f=True) or [None])[0]
    if parent:c.connectAttr(parent+'.worldInverseMatrix[0]',follow+'.matrixIn[2]')
    choice=create('choice','frame')
    if old:c.disconnectAttr(old,ctrl+'.offsetParentMatrix');c.connectAttr(old,choice+'.input[0]')
    else:
        rest=create('holdMatrix','rest');c.setAttr(rest+'.inMatrix',*original,type='matrix');c.connectAttr(rest+'.outMatrix',choice+'.input[0]')
    c.connectAttr(follow+'.matrixSum',choice+'.input[1]')
    c.connectAttr(ns+':worldIK_mode.outColorR',choice+'.selector')
    c.connectAttr(choice+'.output',ctrl+'.offsetParentMatrix')
    for node,visible in ((ctrl,True),(driver,False)):
        for shape in c.listRelatives(node,s=True,f=True) or []:
            p=shape+'.lodVisibility';edge=c.connectionInfo(p,sfd=True)
            if edge:c.disconnectAttr(edge,p)
            c.setAttr(p,visible)
    proxies={}
    for attr in arm_ik.TR:
        name='worldIk'+attr[0].upper()+attr[1:]
        if not c.objExists(ctrl+'.'+name):c.addAttr(ctrl,ln=name,proxy=driver+'.'+attr,keyable=True)
        proxies[driver+'.'+attr]=ctrl+'.'+name
    for p in data['offset_attrs']:
        name=p.rsplit('.',1)[-1]
        if not c.objExists(ctrl+'.'+name):c.addAttr(ctrl,ln=name,proxy=p,keyable=True)
    if not c.objExists(ctrl+'.armSharedWrist'):c.addAttr(ctrl,ln='armSharedWrist',at='message')
    c.connectAttr(root+'.message',ctrl+'.armSharedWrist',force=True)
    shared=dict(control=ctrl,driver=driver,created=created,old_display=old,original_matrix=original,proxies=proxies)
    data['shared_wrist']=shared;data['created'].extend(created);data['version']=arm_ik.VERSION
    data['shapes']=[s for s in data['shapes'] if c.objExists(s) and c.connectionInfo(s+'.lodVisibility',sfd=True)]
    c.setAttr(root+'.armWorldIKData',lock=False);c.setAttr(root+'.armWorldIKData',json.dumps(data),type='string',lock=True)
    return shared


def rebind(root,ctrl):
    import maya.cmds as c
    from .arm_ik import _data
    d=_data(root);old=d.pop('shared_wrist');p=old['control']+'.offsetParentMatrix'
    if c.objExists(p):
        edge=c.connectionInfo(p,sfd=True)
        if edge:c.disconnectAttr(edge,p)
        if old['old_display']:c.connectAttr(old['old_display'],p)
        else:c.setAttr(p,*old['original_matrix'],type='matrix')
    for n in reversed(old['created']):
        if c.objExists(n):c.delete(n)
    d['created']=[n for n in d['created'] if n not in old['created']];d['fk_wrist']=ctrl
    c.setAttr(root+'.armWorldIKData',lock=False);c.setAttr(root+'.armWorldIKData',json.dumps(d),type='string',lock=True)
    return enable(root)


def active(root,role='end_fk'):
    import maya.cmds as c
    from .arm_ik import _data,_mode
    if role!='end_fk' or not c.objExists(root+'.armWorldIKData'):return False
    d=_data(root)
    return bool(d.get('shared_wrist') and _mode(c.getAttr(d['global_plug'])))


def begin(root,setup=None):
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import arm_ik,live_edit,live_arm_manual
    d=arm_ik._data(root);proxy=d['fk_wrist'];source=d['controls']['wrist']
    plugs=[n+'.'+a for n in (proxy,source) for a in arm_ik.TR]
    snapshot=live_edit._snapshot(plugs)
    if setup is not None:
        shared=setup[0];shared[0].update({p:v for p,v in snapshot[0].items() if p not in shared[0]});shared[1].update(snapshot[1]);snapshot=shared
    entry=dict(data={'root':root},role='end_fk',mode=c.contextInfo(c.currentCtx(),c=True),snapshot=snapshot,
               proxy=proxy,source=source,edges=[],curve_edges=[],driver_curve_edges=[],changed=False,finished=False,shared_ik=True,
               setup=(snapshot,True),destinations={},input_basis=om.MMatrix(),native_attrs=arm_ik.TR)
    try:
        display=om.MMatrix(c.xform(proxy,q=True,ws=True,m=True))
        # Isolate the common handle's native input while retaining its FK keys.
        for attr in arm_ik.TR:
            p=proxy+'.'+attr;edge=c.connectionInfo(p,sfd=True)
            if edge:
                value=c.getAttr(p);c.disconnectAttr(edge,p);c.setAttr(p,value);entry['curve_edges'].append((edge,p))
        for attr in arm_ik.TR:
            p=source+'.'+attr;edge=c.connectionInfo(p,sfd=True)
            if edge:
                value=c.getAttr(p);c.disconnectAttr(edge,p);c.setAttr(p,value);entry['driver_curve_edges'].append((edge,p))
        local=om.MTransformationMatrix(om.MMatrix(c.getAttr(proxy+'.matrix')))
        local.setRotation(om.MEulerRotation());c.setAttr(proxy+'.rotate',0,0,0)
        entry['local']=local.asMatrix();entry['parent']=entry['local'].inverse()*display
        entry['display_edge']=c.connectionInfo(proxy+'.offsetParentMatrix',sfd=True)
        parent=(c.listRelatives(proxy,p=True,f=True) or [None])[0]
        entry['native_opm']=entry['parent']*(om.MMatrix(c.getAttr(parent+'.worldInverseMatrix[0]')) if parent else om.MMatrix())
        entry['native_start']=[c.getAttr(proxy+'.'+a) for a in arm_ik.TR];entry['last_native']=list(entry['native_start'])
        live_arm_manual.prepare_native_sample(entry,suspend=False)
        return entry
    except Exception:
        if entry.get('display_edge'):live_arm_manual.restore_display(entry)
        for edge,p in entry['curve_edges']:c.connectAttr(edge,p,force=True)
        for edge,p in entry['driver_curve_edges']:c.connectAttr(edge,p,force=True)
        live_edit._restore(snapshot)
        raise


def reconnect(entry):
    import maya.cmds as c
    from .arm_ik import TR
    # The visible TR input remains the FK animation. IK values are preserved on
    # the same controller through its keyable worldIkTranslate/Rotate proxies.
    values={entry['source']+'.'+a:c.getAttr(entry['source']+'.'+a) for a in TR}
    for edge,p in entry['curve_edges']+entry['driver_curve_edges']:c.connectAttr(edge,p,force=True)
    for a in TR:
        p=entry['proxy']+'.'+a
        if p in entry['snapshot'][0]:c.setAttr(p,entry['snapshot'][0][p])
    for p,v in values.items():c.setAttr(p,v)
    entry['finished']=True
