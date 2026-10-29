"""Keep reverse-foot handles at the same solved reach as the ankle surface.

Only display-frame inputs change. The original solver, authored TR channels,
roll pivots and animation stay intact; playback uses native matrix nodes.
"""
from . import scene_data

MARKER='footReachRoot'


def _choice(control):
    import maya.cmds as c
    follow=c.connectionInfo(control+'.offsetParentMatrix',sfd=True).split('.')[0]
    if not follow or c.nodeType(follow)!='multMatrix':return None
    choice=c.connectionInfo(follow+'.matrixIn[1]',sfd=True).split('.')[0]
    if not choice or c.nodeType(choice)!='choice':return None
    return choice


def ensure(root):
    import maya.cmds as c
    from .live_alignment import _frame
    data=scene_data.read(root+'.liveAlignmentData')
    ankle=data.get('position_targets',{}).get('foot')
    if data['kind']!='leg' or not ankle or not c.objExists(ankle):return []
    targets=[]
    for role in ('heel','toe_end','ball','toe'):
        control=data['controls'].get(role)
        choice=_choice(control) if control and c.objExists(control) else None
        if not choice:continue
        destination=choice+'.input[1]';old=c.connectionInfo(destination,sfd=True)
        if not old:continue
        node=old.split('.')[0]
        if c.objExists(node+'.'+MARKER):
            owner=c.listConnections(node+'.'+MARKER,s=True,d=False) or []
            if owner and c.ls(owner[0],long=True)==c.ls(root,long=True):continue
        targets.append((role,old,destination))
    if not targets:return []
    created=[];edges=[];namespace=root.rsplit('|',1)[-1].rsplit(':',1)[0]
    def create(kind,label):
        node=c.createNode(kind,name=namespace+':solvedFoot_'+label,skipSelect=True)
        created.append(node)
        c.addAttr(node,ln=MARKER,at='message');c.connectAttr(root+'.message',node+'.'+MARKER)
        return node
    c.undoInfo(openChunk=True,chunkName='MatchFootHandleReach')
    try:
        # The foot uses IK orientation but solved joint3 translation. Apply
        # exactly that world-space translation difference to every roll pivot.
        actual=create('pickMatrix','ankle')
        c.connectAttr(ankle+'.worldMatrix[0]',actual+'.inputMatrix')
        requested=create('pickMatrix','input')
        c.connectAttr(_frame(data['targets']['foot'],create),requested+'.inputMatrix')
        for node in (actual,requested):
            for attr in ('useRotate','useScale','useShear'):c.setAttr(node+'.'+attr,False)
        inverse=create('inverseMatrix','inputInverse')
        c.connectAttr(requested+'.outputMatrix',inverse+'.inputMatrix')
        translation=create('multMatrix','translation')
        c.connectAttr(inverse+'.outputMatrix',translation+'.matrixIn[0]')
        c.connectAttr(actual+'.outputMatrix',translation+'.matrixIn[1]')
        for role,old,destination in targets:
            matrix=create('multMatrix',role)
            c.connectAttr(old,matrix+'.matrixIn[0]')
            c.connectAttr(translation+'.matrixSum',matrix+'.matrixIn[1]')
            c.connectAttr(matrix+'.matrixSum',destination,force=True);edges.append((old,destination))
        return created
    except Exception:
        for old,destination in reversed(edges):c.connectAttr(old,destination,force=True)
        if created:c.delete(created)
        raise
    finally:c.undoInfo(closeChunk=True)


def install():
    import maya.cmds as c
    created=[]
    for root in c.ls('::*.liveAlignmentData',objectsOnly=True) or []:created.extend(ensure(root))
    return created


def remove(root):
    """Remove only this display extension before removing a live surface."""
    import maya.cmds as c
    nodes=[n for n in c.listConnections(root+'.message',s=False,d=True) or []
           if c.objExists(n+'.'+MARKER) and c.isConnected(root+'.message',n+'.'+MARKER)]
    nodes=list(dict.fromkeys(nodes))
    for n in nodes:
        if c.nodeType(n)!='multMatrix':continue
        old=c.connectionInfo(n+'.matrixIn[0]',sfd=True)
        if not old:continue
        for dst in c.listConnections(n+'.matrixSum',s=False,d=True,p=True) or []:
            if dst.endswith('.input[1]') and c.nodeType(dst.split('.')[0])=='choice':c.connectAttr(old,dst,force=True)
    if nodes:c.delete(nodes)
    return nodes
