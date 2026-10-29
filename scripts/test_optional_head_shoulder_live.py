"""Disposable integrated rigs; preserve the current scene and its animation."""
import importlib,json,math,runpy,uuid
from pathlib import Path
import maya.cmds as c

def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
def run(mode='head'):
    from maya_agent.rigs import integrated,head_neck,arm_ik
    from maya_agent.rigs.integrated import builder,ui
    for module in (integrated,head_neck,builder,ui):importlib.reload(module)
    suite=runpy.run_path(str(Path(__file__).with_name('test_integrated_rig_live.py')))
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    modified=c.file(q=True,modified=True);auto=c.autoKeyframe(q=True,state=True);busy=arm_ik._busy
    matrices={n:c.xform(n,q=True,ws=True,m=True) for n in c.ls(type='transform',long=True)+c.ls(type='joint',long=True)}
    curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
    results=[];rig=None;arm_ik._busy=True;c.autoKeyframe(state=False)
    def cleanup():
        nonlocal rig
        if rig:suite['remove'](rig);rig=None
        added=set(c.ls(long=True))-before
        for n in list(added):
            if c.objExists(n) and c.objectType(n,isAType='constraint'):c.delete(n)
        for n in sorted(added,key=lambda x:x.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        assert set(c.ls(long=True))==before,'test nodes remain'
    try:
        if mode=='head':
            # Single head with/without torso/root; original 1-neck and multi-neck behavior.
            for count,animated,zero,follow in [(1,False,False,'none'),(1,False,True,'chest'),(1,True,True,'both'),(1,True,False,'root'),(2,True,True,'chest'),(4,True,True,'chest')]:
                prefix='_optionalHead_'+uuid.uuid4().hex[:7];c.currentTime(1)
                root=c.createNode('transform',name=prefix+'_fixture');chest=c.createNode('transform',name=prefix+'_chest',parent=root);c.setAttr(chest+'.ty',10)
                targets=[]
                for i in range(count):
                    target=c.createNode('joint',name=prefix+'_target'+str(i),parent=targets[-1] if targets else chest)
                    c.setAttr(target+'.translate',.2,2.5,.1);c.setAttr(target+'.jointOrient',7,-11,3)
                    targets.append(c.ls(target,long=True)[0])
                if animated:
                    for n in [root,chest]+targets:
                        for attr,amount in [('translateX',.2),('rotateY',12),('rotateZ',-6)]:
                            v=c.getAttr(n+'.'+attr)
                            for t,delta in [(1,0),(3,amount),(5,-amount*.3)]:c.setKeyframe(n,at=attr,t=t,v=v+delta)
                expected={}
                for t in (1,2,3,4,5) if animated else (1,):
                    c.currentTime(t);expected[t]=[c.xform(n,q=True,ws=True,m=True) for n in targets]
                c.currentTime(1);ui.validate_count('head',targets)
                if count==1:
                    try:ui.validate_count('body',targets)
                    except ValueError:pass
                    else:raise AssertionError('body minimum changed')
                options=dict(targets=targets,copy_animation=animated,start_frame=1,end_frame=5,space_head=True)
                rig=builder.build({'head':options},namespace=prefix,zero_controls=zero,chest_follow=chest if follow in ('chest','both') else None,general_root=root if follow in ('root','both') else None)
                part=rig['parts']['head'];assert set(part['controls'])=={'head'}|{'neck'+str(i) for i in range(1,count)}
                assert len(part['neck_groups'])==count-1 and len(part['neck_blends'])==count-1
                if count==1:assert not c.ls(part['namespace']+':neck*'),'unexpected neck nodes'
                peak=0
                for t,poses in expected.items():
                    c.currentTime(t)
                    for n,m in zip(targets,poses):peak=max(peak,error(m,c.xform(n,q=True,ws=True,m=True)))
                assert peak<1e-4,peak
                c.currentTime(1)
                if not animated:
                    ctrl=part.get('zero_controls',part['controls'])['head'];old=c.xform(targets[-1],q=True,ws=True,m=True)
                    c.setAttr(ctrl+'.rotateY',c.getAttr(ctrl+'.rotateY')+20)
                    assert error(old,c.xform(targets[-1],q=True,ws=True,m=True))>.01,'head not editable'
                    if follow=='chest':
                        old=c.xform(targets[-1],q=True,ws=True,t=True);anchor=c.xform(part['head_anchor'],q=True,ws=True,t=True)
                        c.setAttr(chest+'.rotateZ',25);new=c.xform(targets[-1],q=True,ws=True,t=True);next_anchor=c.xform(part['head_anchor'],q=True,ws=True,t=True)
                        assert error([a-b for a,b in zip(new,old)],[a-b for a,b in zip(next_anchor,anchor)])<1e-4
                results.append(dict(count=count,animated=animated,zero=zero,follow=follow,max_error=peak));cleanup()
        else:
            for animated,shoulder in [(False,None),(True,None),(False,'L')]:
                prefix='_optionalShoulder_'+uuid.uuid4().hex[:7];c.currentTime(1)
                fixture,parts=suite['fixture'](prefix,animated,shoulders=True)
                keep={'body','arm_L','arm_R'}|({'shoulder_'+shoulder} if shoulder else set());parts={k:v for k,v in parts.items() if k in keep}
                for key,item in parts.items():
                    if key.startswith('arm'):item.update(space_upper_arm=True,space_wrist=True)
                rig=builder.build(parts,namespace=prefix,zero_controls=True,general_root=fixture)
                assert rig['max_world_error']<1e-4
                chest=rig['parts']['body']['controls']['chest'];c.currentTime(1)
                for side in ('L','R'):
                    arm=rig['parts']['arm_'+side];driver=rig['parts']['shoulder_'+side]['controls']['clavicle'] if shoulder==side else chest
                    link=next(l for l in rig['hierarchy'] if l['part']=='arm_'+side)
                    assert link['driver']==driver,(side,link)
                # Existing chest fallback must carry upper-arm origins on both axes,
                # while retaining native shoulder routing on the side that has one.
                old={s:c.xform(rig['parts']['arm_'+s]['controls']['shoulder_fk'],q=True,ws=True,t=True) for s in ('L','R')}
                loc={s:c.xform(rig['parts']['arm_'+s]['shoulder_locator'],q=True,ws=True,t=True) for s in ('L','R')}
                editable=rig['parts']['body']['zero_controls']['chest'];c.setAttr(editable+'.rotateZ',c.getAttr(editable+'.rotateZ')+15)
                for side in ('L','R'):
                    arm=rig['parts']['arm_'+side];now=c.xform(arm['controls']['shoulder_fk'],q=True,ws=True,t=True);newloc=c.xform(arm['shoulder_locator'],q=True,ws=True,t=True)
                    assert error(now,old[side])>.01,'arm did not follow chest'
                    assert error([a-b for a,b in zip(now,old[side])],[a-b for a,b in zip(newloc,loc[side])])<1e-4,'arm follows twice'
                results.append(dict(animated=animated,shoulder=shoulder,max_error=rig['max_world_error']));cleanup()
    finally:
        cleanup();c.currentTime(frame);c.autoKeyframe(state=auto);arm_ik._busy=busy
        c.select(selection,r=True) if selection else c.select(clear=True)
        for n,keys in curves.items():assert (c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True))==keys,'original curves changed'
        unchanged=max([error(m,c.xform(n,q=True,ws=True,m=True)) for n,m in matrices.items()] or [0])
        assert unchanged<1e-8,unchanged;c.file(modified=modified)
    return dict(passed=True,mode=mode,cases=results,original_matrix_error=unchanged,original_nodes_restored=True,original_curves_restored=True)
