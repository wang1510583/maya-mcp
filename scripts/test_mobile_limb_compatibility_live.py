"""Disposable current-rig export, Android editing and Maya import regression."""
import json,runpy,uuid,subprocess,traceback,math
from pathlib import Path
import maya.cmds as c

ROOT=Path(__file__).resolve().parents[1]
BACK=ROOT/'自定义人物绑定插件/maya_agent/rigs/mobile_io/backend'

def run(java,classpath,output):
    from maya_agent.rigs import integrated,arm_ik,external_constraints,foot_space
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    suite=runpy.run_path(str(ROOT/'scripts/test_integrated_rig_live.py'))
    snapshot=runpy.run_path(str(BACK/'export_snapshot.py'))
    compiler=runpy.run_path(str(BACK/'export_portable_graph.py'))
    animation=runpy.run_path(str(BACK/'export_animation.py'))
    importer=runpy.run_path(str(BACK/'mobile_animation_io.py'))['apply']
    before=snapshot['fingerprint']();uuids=set(c.ls(uuid=True));busy=arm_ik._busy
    original_matrices={n:c.xform(n,q=True,ws=True,m=True) for n in c.ls(type='transform',long=True)+c.ls(type='joint',long=True)}
    playback={a:c.playbackOptions(q=True,**{a:True}) for a in ('minTime','maxTime','animationStartTime','animationEndTime')}
    report={'stages':[]};fixture=rig=None;constraints=[]
    try:
        arm_ik._busy=True;c.autoKeyframe(state=False)
        prefix='_mobileLimb_'+uuid.uuid4().hex[:8]
        fixture,parts=suite['fixture'](prefix,True,shoulders=True)
        for key,p in parts.items():
            p.update(space_head=True,space_chest=True,space_upper_arm=True,space_wrist=True,space_foot=True,space_knee=True)
            if key.startswith(('arm','leg')):p['live_alignment']=True
        c.currentTime(1);c.playbackOptions(minTime=1,maxTime=5,animationStartTime=1,animationEndTime=5)
        rig=integrated.build(parts,namespace=prefix,zero_controls=True)
        old_namespace=c.namespaceInfo(currentNamespace=True);c.namespace(set=prefix)
        try:
            mesh=c.polyCube(name='testMesh',ch=False,w=4,h=10,d=2)[0];c.setAttr(mesh+'.ty',12)
            c.skinCluster([parts['body']['targets'][0],parts['leg_L']['targets'][2],parts['leg_R']['targets'][2]],mesh,tsb=True,name='testSkin')
            c.parent(mesh,fixture)
        finally:c.namespace(set=old_namespace)
        foot_space.switch(rig['parts']['leg_R']['root'],1,key=True)
        controls=[n for p in rig['parts'].values() for n in p['zero_controls'].values()]
        api=runpy.run_path(str(ROOT/'scripts/test_euler_tool_live.py'))['load_tool']()
        for stage in ('plain','euler','constrained','constrained_ik'):
            folder=out/stage;folder.mkdir(exist_ok=True)
            c.currentTime(1)
            if stage=='euler':
                eligible=[n for n in controls if all('rotate'+a in json.loads(c.getAttr(n+'.zeroChannelData'))['offsets'] for a in 'XYZ')]
                for i,n in enumerate(eligible):api['switch_euler_order']([n],api['ROTATE_ORDERS'][1+i%5])
            if stage=='constrained_ik':
                for ctrl in constraints:external_constraints.remove(ctrl)
                constraints=[]
                for side in ('L','R'):arm_ik.switch(rig['parts']['arm_'+side]['root'],1,key=True)
            if stage in ('constrained','constrained_ik'):
                target=c.createNode('transform',name=prefix+'_external',parent=fixture)
                c.setAttr(target+'.rotate',15,23,-8)
                for f,v in ((1,0),(3,.3),(5,-.2)):
                    c.setKeyframe(target,at='tx',t=f,v=v);c.setKeyframe(target,at='ry',t=f,v=23+v*10)
                c.currentTime(1)
                for side in ('L','R'):
                    for role,kind in ((('shoulder_fk','orient'),('middle_fk','parent'),('end_fk','point')) if stage=='constrained' else (('end_fk','parent'),('pole_locator','point'))):
                        ctrl=rig['parts']['arm_'+side]['zero_controls'][role]
                        external_constraints.attach(ctrl,target,kind=kind);constraints.append(ctrl)
                    ctrl=rig['parts']['leg_'+side]['zero_controls']['foot']
                    external_constraints.attach(ctrl,target);constraints.append(ctrl)
            # Build the EM graph after creating/changing disposable constraints.
            c.evaluationManager(invalidate=True);c.dgdirty(allPlugs=True);c.refresh(force=True)
            snapshot['export'](rig['root'],str(folder/'snapshot.json'),selection=[])
            compiler['export'](str(folder/'snapshot.json'),str(folder/'debug.json'))
            compiler['compact'](str(folder/'debug.json'),str(folder/'graph.json'))
            animation['export'](str(folder/'snapshot.json'),str(folder/'graph.json'),str(folder/'animation.json'),str(folder/'reference.json'))
            compiler['package_snapshot'](str(folder/'snapshot.json'),str(folder/'graph.json'),str(folder/'project.mobile.json'),str(folder/'animation.json'))
            debug=json.loads((folder/'debug.json').read_text('utf-8'));cc=compiler['Compiler'](json.loads((folder/'snapshot.json').read_text('utf-8')))
            c.currentTime(3);truth={}
            for op in debug['ops']:
                if op.get('name'):
                    try:truth[op['name']]=cc.value(cc.plug(op['name']))
                    except Exception:pass
            (folder/'truth3.json').write_text(json.dumps(truth),'utf-8');c.currentTime(1)
            logs=[]
            for test,arguments in [('LimbGraphDiagnostic',[str(folder)]),('PortableRigTest',[str(folder/'debug.json'),str(folder/'reference.json'),str(folder/'snapshot.json')]),('LimbCompatibilityTest',[str(folder)])]:
                proc=subprocess.run([java,'-cp',classpath,'com.example.customrigtest.'+test]+arguments,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
                (folder/(test+'.log')).write_text(proc.stdout+proc.stderr,'utf-8')
                assert proc.returncode==0,(stage,test,proc.stdout[-3000:],proc.stderr)
                logs.append(proc.stdout[-200:])
            results=json.loads((folder/'android-results.json').read_text('utf-8'))
            graph=json.loads((folder/'graph.json').read_text('utf-8'))
            guard=rig['parts']['leg_L']['zero_controls']['foot'];order=c.getAttr(guard+'.rotateOrder')
            try:
                c.setAttr(guard+'.rotateOrder',(order+1)%6)
                try:importer(str(folder/'android-edited.json'),dry_run=True,snapshot_path=str(folder/'snapshot.json'))
                except ValueError as exc:assert '旋转顺序' in str(exc)
                else:raise AssertionError('Stale Euler snapshot accepted')
            finally:c.setAttr(guard+'.rotateOrder',order)
            inputs=[op for op in graph['ops'] if op['op']=='input'];edges=[];values={};locks=[]
            maximum=0;worst=None
            snap=json.loads((folder/'snapshot.json').read_text('utf-8'))
            output_nodes={r['id']:r['path'] for r in snap['controls']+snap['joints']}
            def error(row):
                diffs=[(max(abs(a-b) for a,b in zip(matrix,c.xform(output_nodes[uid],q=True,ws=True,m=True))),uid)
                       for uid,matrix in row['outputs'].items() if output_nodes[uid] and len(matrix)==16]
                return max(diffs,default=(0,None))
            importer(str(folder/'android-edited.json'),snapshot_path=str(folder/'snapshot.json'),backup_directory=str(folder/'backups'))
            try:
                roundtrip=0
                for row in results['roundtrip']:
                    c.currentTime(row['frame']);c.refresh(force=True)
                    delta,uid=error(row);roundtrip=max(roundtrip,delta)
                    if delta>=.0005:
                        expected={r['frame']:r['values'] for r in json.loads((folder/'android-edited.json').read_text('utf-8'))['keys']}[row['frame']]
                        differences=[]
                        for op in inputs:
                            d=op['data'];axis=d['axis'];wanted=d['base']*(180/math.pi if axis<3 else 1)+expected.get(d['id'],{}).get(animation['ATTRS'][axis],0)
                            actual=c.getAttr(op['name'])
                            if abs(actual-wanted)>.0001:differences.append(dict(plug=op['name'],actual=actual,expected=wanted))
                        (folder/'input-mismatch.json').write_text(json.dumps(differences,indent=2),'utf-8')
                        differences=[]
                        for op in graph['ops']:
                            name=op.get('name','')
                            if name not in row['operations']:continue
                            try:actual=cc.value(cc.plug(name))
                            except Exception:continue
                            expected=row['operations'][name]
                            if len(actual)==len(expected) and max(abs(a-b) for a,b in zip(actual,expected))>.0001:
                                node=name.split('.')[0]
                                extras={a:c.getAttr(node+'.'+a) for a in ('nodeState','enableRestPosition','restTranslate','constraintOffsetPolarity') if c.objExists(node+'.'+a)}
                                differences.append(dict(name=name,kind=op['op'],actual=actual,expected=expected,extras=extras))
                        (folder/'op-mismatch.json').write_text(json.dumps(differences[:40],indent=2),'utf-8')
                    assert delta<.0005,(stage,'roundtrip',row['frame'],uid,delta)
            finally:
                # Time changes must not hide the import chunk from Undo.
                c.undoInfo(stateWithoutFlush=False)
                c.currentTime(1)
                c.undoInfo(stateWithoutFlush=True)
            # Import is the last undoable edit only if time changes are disabled;
            # restore original animation using its original-curve payload instead.
            importer(str(folder/'animation.json'),snapshot_path=str(folder/'snapshot.json'),backup_directory=str(folder/'restore-backups'))
            try:
                for op in inputs:
                    plug=op['name'];values[plug]=c.getAttr(plug);edge=c.connectionInfo(plug,sfd=True)
                    if c.getAttr(plug,lock=True):c.setAttr(plug,lock=False);locks.append(plug)
                    if edge:c.disconnectAttr(edge,plug);edges.append((edge,plug))
                for row in results['cases']:
                    for op in inputs:
                        data=op['data'];axis=data['axis'];delta=row['inputs'].get(data['id'],{}).get(animation['ATTRS'][axis],0)
                        c.setAttr(op['name'],data['base']*(180/math.pi if axis<3 else 1)+delta)
                    delta,uid=error(row)
                    if delta>maximum:maximum=delta;worst=(row['label'],uid)
                    assert delta<.0005,(stage,row['label'],uid,delta)
            finally:
                for plug,value in values.items():c.setAttr(plug,value)
                for src,dst in edges:c.connectAttr(src,dst)
                for plug in locks:c.setAttr(plug,lock=True)
                c.dgdirty(allPlugs=True);c.currentTime(2);c.currentTime(1);c.refresh(force=True)
            report['stages'].append(dict(stage=stage,cases=len(results['cases']),maxGestureError=maximum,worst=worst,maxRoundtripError=roundtrip))
            (out/'progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        report['passed']=True
    except Exception:
        report['passed']=False;report['traceback']=traceback.format_exc()
    finally:
        for ctrl in constraints:
            if external_constraints.registry(ctrl):external_constraints.remove(ctrl)
        if rig:suite['remove'](rig)
        if fixture and c.objExists(fixture):c.delete(fixture)
        for uid in set(c.ls(uuid=True))-uuids:
            nodes=c.ls(uid,l=True) or []
            if nodes and c.nodeType(nodes[0]).startswith('animCurve') and not c.listConnections(nodes[0]+'.output',s=False,d=True):c.delete(nodes[0])
        c.playbackOptions(**playback);c.currentTime(before['frame']);c.select(before['selection'],r=True) if before['selection'] else c.select(clear=True)
        c.autoKeyframe(state=before['autoKey']);c.file(modified=before['modified']);arm_ik._busy=busy;arm_ik.install()
        after=snapshot['fingerprint']();report['sceneRestored']=all(before[k]==after[k] for k in before if k!='transformsHash')
        report['matrixExact']=before['transformsHash']==after['transformsHash']
        report['originalMatrixError']=max(abs(a-b) for n,m in original_matrices.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        report['sceneRestored']=report['sceneRestored'] and report['originalMatrixError']<1e-8
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return report
