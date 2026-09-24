"""Run in Maya. Reject unsuitable targets without editing the user's scene."""
import uuid
import maya.cmds as c
from maya_agent.rigs.custom_body import build
from maya_agent.rigs.custom_body.targets import ordered_selection

prefix='_CBR_GUARD_'+uuid.uuid4().hex[:8]
before=set(c.ls(long=True))
selection=c.ls(selection=True,long=True) or []
dirty=c.file(query=True,modified=True)
owned=[]
checks=[]


def reject(targets, label):
    current=set(c.ls(long=True))
    try:
        unexpected = build(namespace=prefix,targets=targets)
    except ValueError:
        pass
    else:
        for node in reversed(unexpected['nodes']):
            if c.objExists(node): c.delete(node)
        if c.namespace(exists=unexpected['namespace']): c.namespace(removeNamespace=unexpected['namespace'])
        raise AssertionError('Accepted '+label)
    assert set(c.ls(long=True))==current
    assert not c.namespace(exists=prefix)
    checks.append(label)


try:
    a=c.createNode('transform',name=prefix+'_a');owned.append(a)
    b=c.createNode('transform',name=prefix+'_b');owned.append(b)
    c.setAttr(b+'.translateY',3)
    reject([a],'too few targets')
    reject([a,a],'duplicates')
    reject([a, prefix+'_missing'],'missing target')
    reject([a,b+'.vtx[0]'],'components')
    c.setAttr(b+'.translateX',lock=True)
    reject([a,b],'locked channel')
    c.setAttr(b+'.translateX',lock=False)
    c.setKeyframe(b,attribute='translateX',time=1,value=0)
    anim=c.listConnections(b+'.translateX',source=True,destination=False)[0];owned.append(anim)
    reject([a,b],'animated target')
    c.delete(anim)
    parent=c.createNode('transform',name=prefix+'_parent');owned.append(parent)
    c.parent(b,parent)
    c.setKeyframe(parent,attribute='rotateY',time=1,value=0)
    parent_anim=c.listConnections(parent+'.rotateY',source=True,destination=False)[0];owned.append(parent_anim)
    reject([a,b],'animated ancestor')
    c.delete(parent_anim)
    c.parent(b,world=True)
    constraint=c.parentConstraint(a,b,maintainOffset=True)[0];owned.append(constraint)
    reject([a,b],'already constrained target')
    c.delete(constraint)
    c.setAttr(b+'.scaleX',2)
    reject([a,b],'nonuniform scale')
    c.setAttr(b+'.scaleX',1)
    c.setAttr(b+'.translateY',0)
    reject([a,b],'coincident adjacent targets')
    c.setAttr(b+'.translateY',3)
    c.parent(b,a,add=True)
    reject([a,'|'+b],'instanced target')
finally:
    for node in reversed(owned):
        if c.objExists(node): c.delete(node)
    c.select(selection,replace=True) if selection else c.select(clear=True)
    assert set(c.ls(long=True))==before
    c.file(modified=dirty)
result={'checks':checks,'scene_preserved':True}
