"""Maya-only rejection and capture-failure rollback checks on owned targets."""
import uuid
import maya.cmds as c
from maya_agent.rigs.custom_body import build
from maya_agent.rigs.custom_body.animation import Transfer
prefix='_CBR_ANIM_GUARD_'+uuid.uuid4().hex[:8]
before=set(c.ls(long=True))
selection=c.ls(sl=True,long=True) or []
time=c.currentTime(q=True)
dirty=c.file(q=True,modified=True)
checks=[]

def reject(nodes,label):
    baseline=set(c.ls(long=True))
    try:
        build(namespace=prefix,targets=nodes,copy_animation=True,start_frame=1,end_frame=3)
    except ValueError:
        pass
    else: raise AssertionError('Accepted '+label)
    assert set(c.ls(long=True))==baseline
    checks.append(label)

try:
    a=c.createNode('transform',name=prefix+'_a')
    b=c.createNode('transform',name=prefix+'_b')
    c.setAttr(b+'.translateY',3)
    c.setKeyframe(b,at='scaleX',t=1,v=2)
    curve=c.listConnections(b+'.scaleX',s=True,d=False)[0]
    c.currentTime(1)
    reject([a,b],'nonuniform scale')
    c.delete(curve)
    c.setAttr(b+'.scaleX',1)
    c.currentTime(time)
    constraint=c.parentConstraint(a,b,mo=True)[0]
    reject([a,b],'existing constraint')
    c.delete(constraint)
    sdk=c.createNode('animCurveUL',name=prefix+'_sdk')
    c.connectAttr(a+'.translateX',sdk+'.input')
    c.connectAttr(sdk+'.output',b+'.translateX')
    reject([a,b],'set driven key')
    c.delete(sdk)
    blend=c.createNode('animBlendNodeAdditiveDL',name=prefix+'_blend')
    c.connectAttr(blend+'.output',b+'.translateX')
    reject([a,b],'animation layer blend input')
    c.delete(blend)
    c.setKeyframe(b,at='translateX',t=1,v=1)
    c.setKeyframe(b,at='translateX',t=3,v=2)
    src=c.connectionInfo(b+'.translateX',sourceFromDestination=True)
    fixture=set(c.ls(long=True))
    previous=Transfer.capture
    def injected(self):
        previous(self)
        raise RuntimeError('capture injected failure')
    Transfer.capture=injected
    try:
        try: build(namespace=prefix,targets=[a,b],copy_animation=True,start_frame=1,end_frame=3)
        except RuntimeError as exc: assert 'capture injected failure' in str(exc)
        else: raise AssertionError('Missing failure')
    finally: Transfer.capture=previous
    assert c.isConnected(src,b+'.translateX')
    assert set(c.ls(long=True))==fixture
    assert c.currentTime(q=True)==time
    checks.append('capture failure restores nodes time and inputs')
finally:
    for n in reversed(c.ls(long=True)):
        if n not in before and c.objExists(n): c.delete(n)
    if c.namespace(exists=prefix): c.namespace(removeNamespace=prefix)
    c.currentTime(time)
    c.select(selection,r=True) if selection else c.select(clear=True)
    c.file(modified=dirty)
    assert set(c.ls(long=True))==before
result={'checks':checks,'passed':True}
