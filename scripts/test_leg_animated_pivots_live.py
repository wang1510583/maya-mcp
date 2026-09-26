"""Continuous pivot compensation: motion, repeat edits, new rotation and rollback."""
import math
import uuid
import maya.cmds as c


def verify():
    from maya_agent.rigs.soft_leg import _build_template,cleanup,set_adjustment_mode
    from maya_agent.rigs.soft_leg.adjustment import resolve
    from maya_agent.rigs.soft_leg.pivot_animation import Edit
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or []
    frame=c.currentTime(q=True);auto=c.autoKeyframe(q=True,state=True)
    ns='_pivotAnimation_'+uuid.uuid4().hex[:8]
    rig=None
    times=[-12.5,0,1.25,1.4,2.13,3.77,5.5,9.2,16.7,30.6]
    def matrices(nodes):return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def motion(nodes):
        result={}
        for f in times:c.currentTime(f);result[f]=matrices(nodes)
        return result
    def compare(expected):
        maximum=0
        for f,poses in expected.items():
            c.currentTime(f)
            for n,m in poses.items():
                error=max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))
                assert error<1e-5,(f,n,error)
                maximum=max(maximum,error)
        return maximum
    try:
        c.autoKeyframe(state=False)
        rig=_build_template(ns,offset=(40,0,0))
        root,data=resolve(rig)
        for i,key in enumerate(('heel','toe_end','toe','foot')):
            node=rig['controls'][key]
            c.setAttr(node+'.rotateOrder',i)
            for attr,values in [('rotateX',[0,12,-9]),('rotateY',[0,-6,8]),('rotateZ',[0,3,-4])]:
                for f,v in zip([1.25,5.5,9.2],values):c.setKeyframe(node,at=attr,t=f,v=v)
                c.setInfinity(node,attribute=attr,preInfinite='cycle',postInfinite='cycle')
        for f,v in [(1.25,0),(5.5,.3),(9.2,-.1)]:c.setKeyframe(rig['controls']['foot'],at='translateX',t=f,v=v)
        # Keep animated scale on toe: orientation is driven from it while the
        # two-bone solver remains rigid. This also exercises scale-pivot changes.
        for axis in 'XYZ':
            for f,v in [(1.25,1),(5.5,1.2),(9.2,.9)]:c.setKeyframe(rig['controls']['toe'],at='scale'+axis,t=f,v=v)
        curves=c.ls(ns+':*',type='animCurve') or []
        curves+=c.listConnections(list(rig['controls'].values()),s=True,d=False,type='animCurve') or []
        curve_data={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True)) for n in set(curves)}
        nodes=rig['joints']+list(data['controls'].values())
        original=motion(nodes)
        errors=[]
        for iteration in range(2):
            c.currentTime(3.77)
            set_adjustment_mode(root,True)
            desired={}
            for i,key in enumerate(data['guides']):
                c.move(.13*(i+1),.07,.3 if key!='heel' else -.3,data['guides'][key],r=True,ws=True)
                desired[key]=c.xform(data['guides'][key],q=True,ws=True,t=True)
            set_adjustment_mode(root,False)
            for key,p in desired.items():assert math.dist(c.xform(data['controls'][key],q=True,ws=True,rp=True),p)<1e-5
            errors.append(compare(original))
        for n,expected in curve_data.items():
            assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True),c.keyTangent(n,q=True,itt=True),c.keyTangent(n,q=True,ott=True))==expected
        # An added rotation key must use the new pivot, not get cancelled by a
        # compensation graph that incorrectly reads the live rotation channel.
        c.currentTime(5.5)
        heel=data['controls']['heel'];pivot=c.xform(heel,q=True,ws=True,rp=True)
        matrix=c.xform(rig['joints'][2],q=True,ws=True,m=True)
        value=c.getAttr(heel+'.rotateX')
        c.setKeyframe(heel,at='rotateX',t=5.5,v=value+10);c.dgdirty(heel)
        assert math.dist(pivot,c.xform(heel,q=True,ws=True,rp=True))<1e-5
        assert max(abs(a-b) for a,b in zip(matrix,c.xform(rig['joints'][2],q=True,ws=True,m=True)))>.01
        c.setKeyframe(heel,at='rotateX',t=5.5,v=value);c.dgdirty(heel)
        expected=motion(nodes)
        c.currentTime(3.77)
        set_adjustment_mode(root,True)
        c.move(1,2,3,data['guides']['toe'],r=True,ws=True)
        set_adjustment_mode(root,False,cancel=True)
        compare(expected)
        # Inject failure after one graph has been attached. Original graphs and
        # every curve must survive cleanup; the mode stays open for correction.
        set_adjustment_mode(root,True)
        c.move(.2,0,.1,data['guides']['heel'],r=True,ws=True)
        snapshot=set(c.ls(long=True))
        apply=Edit.apply
        def broken(self,node,position):
            apply(self,node,position)
            raise RuntimeError('injected pivot failure')
        Edit.apply=broken
        try:
            try:set_adjustment_mode(root,False)
            except RuntimeError as exc:assert 'injected pivot failure' in str(exc)
            else:raise AssertionError('Expected rollback')
        finally:Edit.apply=apply
        assert set(c.ls(long=True))==snapshot
        compare(expected)
        set_adjustment_mode(root,False,cancel=True)
        return dict(passed=True,max_error=max(errors),subframes_and_infinity=True,
                    original_curves_unchanged=True,repeated_edits=True,new_rotation_uses_new_pivot=True,
                    cancellation=True,failure_rollback=True)
    finally:
        if rig:cleanup(ns)
        # Maya may put automatically created curves outside the namespace.
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
