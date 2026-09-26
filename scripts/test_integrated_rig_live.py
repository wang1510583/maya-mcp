"""Six-part assembly in the running Maya without replacing the user's scene."""
import math
import uuid
import maya.cmds as c


def fixture(prefix,animated=False,shoulders=False):
    root=c.createNode('transform',name=prefix+'_fixture')
    positions={'body':[(0,18,0),(0,20,0),(0,22,0),(0,24,0)],'head':[(0,26,0),(0,29,0)],
               'arm_R':[(-3,24,0),(-7,23,1),(-10,22,0)],'arm_L':[(3,24,0),(7,23,1),(10,22,0)],
               'leg_R':[(-2,18,0),(-2,10,1),(-2,2,0),(-2,.5,3)],'leg_L':[(2,18,0),(2,10,1),(2,2,0),(2,.5,3)]}
    if shoulders:
        positions=dict(list(positions.items())[:2]+[('shoulder_R',[(-1,24,0)]),('shoulder_L',[(1,24,0)])]+list(positions.items())[2:])
    parts={}
    for key,points in positions.items():
        parent=parts['body']['targets'][0 if key.startswith('leg') else -1] if key!='body' else root
        if shoulders and key.startswith('arm'):parent=parts['shoulder_'+key[-1]]['targets'][0]
        nodes=[]
        for i,point in enumerate(points):
            node=c.createNode('joint',name=prefix+'_'+key+str(i),parent=nodes[-1] if nodes else parent)
            c.xform(node,ws=True,t=point);nodes.append(c.ls(node,long=True)[0])
        parts[key]=dict(targets=nodes,copy_animation=animated,connected=key!='leg_L',start_frame=1,end_frame=5,sample_step=1)
    if animated:
        for key,part in parts.items():
            for i,n in enumerate(part['targets']):
                for a,delta in [('translateX',.03),('rotateY',3+i),('rotateZ',1+i*.2)]:
                    value=c.getAttr(n+'.'+a)
                    for f,v in [(1,value),(3,value+delta),(5,value-delta*.3)]:c.setKeyframe(n,at=a,t=f,v=v)
        for f,v in [(1,0),(3,.7),(5,.2)]:c.setKeyframe(root,at='translateZ',t=f,v=v)
    return root,parts


def remove(result):
    from maya_agent.rigs.soft_leg import cleanup
    nspaces=[r['namespace'] for r in result['parts'].values()]
    if result['reference_body']:nspaces.append(result['reference_body']['namespace'])
    nspaces.append(result['namespace'])
    for backup in result['original_animation_backups']:
        pairs=c.listConnections(backup+'.sourceCurves',s=True,d=False,p=True,c=True) or []
        for dst,src in zip(pairs[::2],pairs[1::2]):c.disconnectAttr(src,dst)
    for ns in nspaces:
        for n in c.ls(ns+':*',type='constraint',long=True) or []:
            if c.objExists(n):c.delete(n)
    for ns in nspaces:cleanup(ns)


def verify(animated=False,fail=False):
    from maya_agent.rigs.integrated import builder
    prefix='_integratedTest_'+uuid.uuid4().hex[:7]
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    old_create=builder.create_part;old_constraint=c.parentConstraint
    try:
        fixture_root,parts=fixture(prefix,animated);c.currentTime(1)
        all_targets=[n for p in parts.values() for n in p['targets']]
        poses={n:c.xform(n,q=True,ws=True,m=True) for n in all_targets}
        fixture_nodes=set(c.ls(long=True))
        edges={n+'.'+a:c.connectionInfo(n+'.'+a,sourceFromDestination=True) for n in all_targets for a in ('translateX','rotateY','rotateZ')}
        if fail=='late':
            def broken_constraint(*args,**kwargs):
                if kwargs.get('name')==prefix+':arm_R_target2':raise RuntimeError('injected assembly failure')
                return old_constraint(*args,**kwargs)
            c.parentConstraint=broken_constraint
        elif fail:
            def broken(key,*args,**kwargs):
                if key=='leg_R':raise RuntimeError('injected assembly failure')
                return old_create(key,*args,**kwargs)
            builder.create_part=broken
        try:
            rig=builder.build(parts,namespace=prefix)
            assert not fail
        except RuntimeError as exc:
            if not fail or 'injected assembly failure' not in str(exc):raise
            assert set(c.ls(long=True))==fixture_nodes
            assert all(c.connectionInfo(dst,sourceFromDestination=True)==src for dst,src in edges.items())
        finally:builder.create_part=old_create;c.parentConstraint=old_constraint
        if not rig:return dict(passed=True,rollback=True,animated=animated)
        for n,m in poses.items():assert max(abs(a-b) for a,b in zip(c.xform(n,q=True,ws=True,m=True),m))<1e-4,n
        # At a sample frame, move chest and hips. Linked parts must follow once;
        # the deliberately disconnected left leg must remain in world space.
        chest=rig['parts']['body']['controls']['chest'];hips=rig['parts']['body']['controls']['hips']
        def target_positions():return {k:[c.xform(n,q=True,ws=True,t=True) for n in p['targets']] for k,p in parts.items()}
        c.currentTime(3 if animated else 1);old=target_positions()
        def add(node,attr,value):
            if c.listConnections(node+'.'+attr,s=True,d=False):c.setKeyframe(node,at=attr,t=c.currentTime(q=True),v=c.getAttr(node+'.'+attr)+value);c.dgdirty(node)
            else:c.setAttr(node+'.'+attr,c.getAttr(node+'.'+attr)+value)
        add(chest,'translateX',1)
        moved=target_positions()
        for key in ('arm_L','arm_R','head'):
            delta=[b-a for a,b in zip(old[key][0],moved[key][0])]
            assert abs(delta[0]-1)<1e-4 and abs(delta[1])+abs(delta[2])<1e-4,(key,delta)
        for a,b in zip(old['leg_L'],moved['leg_L']):assert math.dist(a,b)<1e-4,('independent leg',a,b)
        old=target_positions();add(hips,'translateZ',1);moved=target_positions()
        for a,b in zip(old['leg_R'],moved['leg_R']):assert abs(b[2]-a[2]-1)<1e-4,('connected leg',a,b)
        for a,b in zip(old['leg_L'],moved['leg_L']):assert math.dist(a,b)<1e-4,('independent leg',a,b)
        import maya.api.OpenMaya as om
        old=target_positions();anchor=om.MMatrix(c.xform(chest,q=True,ws=True,m=True))
        add(chest,'rotateY',15)
        delta=anchor.inverse()*om.MMatrix(c.xform(chest,q=True,ws=True,m=True));moved=target_positions()
        for key in ('head','arm_R','arm_L'):
            for a,b in zip(old[key],moved[key]):
                point=om.MPoint(a)*delta
                assert math.dist([point.x,point.y,point.z],b)<1e-4,(key,a,b,list(point))
        return dict(passed=True,animated=animated,parts=len(rig['parts']),max_error=rig['max_world_error'],
                    connected_follow=True,rotation_follow=True,independent_leg=True,shared_source_hierarchy=True)
    finally:
        builder.create_part=old_create;c.parentConstraint=old_constraint
        if rig:remove(rig)
        # Everything in this fixture is new and selected source nodes are not among it.
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before


def verify_shoulders(animated=False,general=False):
    from maya_agent.rigs.integrated import builder
    before=set(c.ls(long=True));frame=c.currentTime(q=True);selection=c.ls(sl=True,long=True) or []
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    prefix='_shoulderTest_'+uuid.uuid4().hex[:7]
    try:
        root,parts=fixture(prefix,animated,shoulders=True);c.currentTime(1)
        for part in parts.values():
            part.update(space_head=True,space_chest=True,space_upper_arm=True,space_wrist=True,space_foot=True)
        if general:parts={k:v for k,v in parts.items() if k!='body'}
        rig=builder.build(parts,namespace=prefix,general_root=root if general else None)
        assert len(rig['spaces'])==(7 if general else 8),rig['spaces']
        for space in rig['spaces']:
            initial=c.xform(space['group'],q=True,ws=True,m=True)
            c.setAttr(space['attribute'],1)
            assert max(abs(a-b) for a,b in zip(initial,c.xform(space['group'],q=True,ws=True,m=True)))<1e-4
            # The active alternate target must actually drive the group, not just
            # expose a disconnected attribute or a zero-total-weight constraint.
            alt=c.parentConstraint(space['constraint'],q=True,targetList=True)[1]
            val=c.getAttr(alt+'.translateX');c.setAttr(alt+'.translateX',val+.7)
            assert math.dist(c.xform(alt,q=True,ws=True,t=True),c.xform(space['group'],q=True,ws=True,t=True))<1e-4
            c.setAttr(alt+'.translateX',val);c.setAttr(space['attribute'],0)
        if animated:
            from maya_agent.rigs.soft_leg import set_adjustment_mode
            leg=rig['parts']['leg_L'];nodes=parts['leg_L']['targets'];poses={}
            for f in (1,2.5,5):
                c.currentTime(f);poses[f]=[c.xform(n,q=True,ws=True,m=True) for n in nodes]
            c.currentTime(1)
            mode=set_adjustment_mode(leg,True)
            guide=mode['guides']['heel'];p=c.xform(guide,q=True,ws=True,t=True)
            c.xform(guide,ws=True,t=(p[0]+.2,p[1],p[2]-.1));set_adjustment_mode(leg,False)
            for f,matrices in poses.items():
                c.currentTime(f)
                for n,m in zip(nodes,matrices):assert max(abs(a-b) for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))<1e-4
            c.currentTime(1)
        for side in 'RL':
            arm=rig['parts']['arm_'+side];shoulder=rig['parts']['shoulder_'+side]
            assert c.listRelatives(arm['shoulder_locator'],p=True)[0]==shoulder['controls']['clavicle']
            assert c.listConnections(arm['shoulder_locator'],s=True,d=False,type='parentConstraint')
            ctrl=shoulder['controls']['clavicle'];n=parts['arm_'+side]['targets'][0]
            old=c.xform(n,q=True,ws=True,t=True)
            value=c.getAttr(ctrl+'.translateX')
            if animated:c.setKeyframe(ctrl,at='translateX',t=1,v=value+1);c.dgdirty(ctrl)
            else:c.setAttr(ctrl+'.translateX',value+1)
            new=c.xform(n,q=True,ws=True,t=True)
            assert abs(new[0]-old[0]-1)<1e-4,(side,old,new)
            # Locator bridge transfers the arm base position, not clavicle rotation.
            fk=arm['controls']['shoulder_fk'];oldrot=c.xform(fk,q=True,ws=True,ro=True)
            value=c.getAttr(ctrl+'.rotateZ')
            if animated:c.setKeyframe(ctrl,at='rotateZ',t=1,v=value+15);c.dgdirty(ctrl)
            else:c.setAttr(ctrl+'.rotateZ',value+15)
            assert max(abs(a-b) for a,b in zip(oldrot,c.xform(fk,q=True,ws=True,ro=True)))<1e-4
            assert c.getAttr(arm['shoulder_locator']+'.visibility')
        # Explicit dual weights sum to one for every slider value.
        for space in rig['spaces']:
            aliases=c.parentConstraint(space['constraint'],q=True,weightAliasList=True)
            for value in (0,.25,1):
                c.setAttr(space['attribute'],value)
                weights=[c.getAttr(space['constraint']+'.'+a) for a in aliases]
                assert abs(weights[0]-(1-value))+abs(weights[1]-value)<1e-7
            c.setAttr(space['attribute'],0)
        return dict(passed=True,animated=animated,general_root=general,shoulder_locators=True,
                    shoulder_follow=True,multispaces=len(rig['spaces']),max_error=rig['max_world_error'])
    finally:
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before


def verify_general_root(animated=False):
    from maya_agent.rigs.integrated import build
    before=set(c.ls(long=True));selection=c.ls(sl=True,long=True) or [];frame=c.currentTime(q=True)
    auto=c.autoKeyframe(q=True,state=True);c.autoKeyframe(state=False);rig=None
    prefix='_generalRoot_'+uuid.uuid4().hex[:7]
    try:
        fixture_root,parts=fixture(prefix,animated);c.currentTime(1)
        parts={k:v for k,v in parts.items() if k in ('head','arm_R','leg_L')}
        rig=build(parts,namespace=prefix,general_root=fixture_root)
        assert rig['general_root']==c.ls(fixture_root,long=True)[0]
        assert set(rig['parts'])==set(parts)
        snapshots={k:[c.xform(n,q=True,ws=True,t=True) for n in p['targets']] for k,p in parts.items()}
        attr=fixture_root+'.translateX'
        c.setAttr(attr,c.getAttr(attr)+2)
        for key,p in parts.items():
            actual=[c.xform(n,q=True,ws=True,t=True) for n in p['targets']]
            for a,b in zip(snapshots[key],actual):
                assert abs(b[0]-a[0]-(0 if key=='leg_L' else 2))<1e-4,(key,a,b)
        return dict(passed=True,animated=animated,general_root=True,connected_follow=True,disconnected_independent=True,
                    skipped_unloaded=True,max_error=rig['max_world_error'])
    finally:
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(selection,r=True) if selection else c.select(clear=True)
        assert set(c.ls(long=True))==before
