"""Compare generated head/neck against the reference's actual constraint behavior."""
import math,uuid,json
from pathlib import Path
import maya.cmds as c


def verify():
    from maya_agent.rigs.head_neck import build
    from maya_agent.rigs.soft_leg import cleanup
    import maya.api.OpenMaya as om
    before=set(c.ls(long=True));frame=c.currentTime(q=True);sel=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False)
    ns='_headBehavior_'+uuid.uuid4().hex[:7];ref=ns+'_ref';rig=None
    try:
        c.namespace(add=ref)
        def node(name,parent=None,joint=False,matrix=None):
            n=c.createNode('joint' if joint else 'transform',name=ref+':'+name,**({'parent':parent} if parent else {}))
            if matrix:c.xform(n,ws=True,m=matrix)
            return n
        matrices={n:c.xform(n,q=True,ws=True,m=True) for n in ['Chest_ctr1','spine_03','neck_01','head','Head_ctr1','neck_ctr1','main1']}
        root=node('main',matrix=matrices['main1'])
        chest=node('chest',matrix=matrices['Chest_ctr1'])
        chest_joint=node('chest_joint',joint=True,matrix=matrices['spine_03'])
        c.parentConstraint(chest,chest_joint,mo=True)
        neck_joint=node('neck_joint',chest_joint,True,matrices['neck_01'])
        head_joint=node('head_joint',neck_joint,True,matrices['head'])
        head=node('head_control',root,matrix=matrices['Head_ctr1'])
        blend=node('neck_blend',root,matrix=matrices['neck_ctr1'])
        neck=node('neck_control',blend,matrix=matrices['neck_ctr1'])
        con=c.orientConstraint(chest,head,blend,mo=False)[0];c.setAttr(con+'.interpType',2)
        c.pointConstraint(neck_joint,blend,mo=False)
        c.orientConstraint(neck,neck_joint,mo=True)
        c.orientConstraint(head,head_joint,mo=True)
        c.pointConstraint(head_joint,head,mo=False)
        poses=[];targets=[]
        for i,n in enumerate([neck_joint,head_joint]):
            m=c.xform(n,q=True,ws=True,m=True)
            rotation=list(om.MTransformationMatrix(om.MMatrix(m)).rotation(asQuaternion=True).asMatrix())
            poses.append(dict(matrix=m,rotation=rotation,pivot=m[12:15]))
            targets.append(node('output'+str(i),matrix=m))
        item=dict(options={},frames=[],motion={frame:poses})
        rig=build(item,targets,ns,chest=chest)
        newhead=rig['controls']['head'];newneck=rig['controls']['neck1']
        baseline={n:c.getAttr(n+'.rotate')[0] for n in [chest,head,neck,newhead,newneck]}
        cases=[('chest',chest,chest),('head',head,newhead),('neck',neck,newneck)]
        errors={}
        for label,old,new in cases:
            for axis in range(3):
                for n,r in baseline.items():c.setAttr(n+'.rotate',*r,type='double3')
                for n in set([old,new]):c.setAttr(n+'.rotate'+'XYZ'[axis],baseline[n][axis]+30)
                c.dgdirty(allPlugs=True)
                errors[label+'_'+'XYZ'[axis]]=max(abs(a-b) for src,dst in zip([neck_joint,head_joint],targets) for a,b in zip(c.xform(src,q=True,ws=True,m=True),c.xform(dst,q=True,ws=True,m=True)))
        for n,r in baseline.items():c.setAttr(n+'.rotate',*r,type='double3')
        for old,new,xyz in [(chest,chest,(20,-15,10)),(head,newhead,(-25,35,15)),(neck,newneck,(12,18,-9))]:
            for n in set([old,new]):c.setAttr(n+'.rotate',*[a+b for a,b in zip(baseline[n],xyz)],type='double3')
        errors['combined']=max(abs(a-b) for src,dst in zip([neck_joint,head_joint],targets) for a,b in zip(c.xform(src,q=True,ws=True,m=True),c.xform(dst,q=True,ws=True,m=True)))
        report=dict(max_error=max(errors.values()),cases=errors)
        Path('D:/MAYA/MayaAgent-main/MayaAgent-main/outputs/head_behavior_comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        assert report['max_error']<1e-4,report
        return report
    finally:
        for namespace in (ns,ref):
            for n in c.ls(namespace+':*',type='constraint') or []:
                if c.objExists(n):c.delete(n)
        for namespace in (ns,ref):
            if c.namespace(exists=namespace):cleanup(namespace)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(clear=True)
        assert set(c.ls(long=True))==before
