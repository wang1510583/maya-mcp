"""Maya regression: old keys beyond a short BIP must not pull its tail."""
import uuid


def run():
    import maya.cmds as c
    from maya_agent.rigs import bip_sparse
    ns='bipSparseBoundary_'+uuid.uuid4().hex[:10]
    old=c.currentTime(q=True)
    c.namespace(add=ns)
    node=c.createNode('transform',name=ns+':control',skipSelect=True)
    try:
        plugs=[node+'.translateX',node+'.rotateY']
        for plug in plugs:
            for f,value in [(-10,-50),(0,0),(10,20),(40,100)]:c.setKeyframe(plug,t=f,v=value)
        class Baker:pass
        baker=Baker();baker.plugs=plugs;baker.parts={'body':{'namespace':ns}};baker.mode_plugs=[]
        samples=[(f,{p:min(f,10)*2. for p in plugs}) for f in range(31)]
        result=bip_sparse.apply(baker,samples,{'body':[0.,10.]})
        for plug in plugs:
            assert c.keyframe(plug,q=True,tc=True)==[-10.,0.,10.,40.]
            assert c.keyframe(plug,q=True,vc=True,time=(40,40))==[100.]
            for f in [10,10.25,15,20.5,30]:
                c.currentTime(f)
                assert abs(c.getAttr(plug)-20)<1e-8,(plug,f,c.getAttr(plug))
        return result
    finally:
        curves=c.listConnections(node,s=True,d=False,type='animCurve') or []
        c.delete(node,curves);c.namespace(removeNamespace=ns);c.currentTime(old)
