"""Run in a separate Maya GUI process using a clean preference directory."""
import json,math,sys,traceback,runpy,os,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('BENCAO_TEST_OUT',str(ROOT/'outputs'/'runtime-assistant-test')))


def run():
    import maya.cmds as c
    import maya.api.OpenMaya as om
    assert not any(n.startswith('maya_agent.rigs') for n in sys.modules),'full rig already loaded'
    # Installer and activation before opening a file must also work.
    single_file=os.environ.get('BENCAO_TEST_SINGLE_FILE')=='1'
    if single_file:
        dropped=OUT/'单独拖入测试.py'
        shutil.copyfile(ROOT/'本草角色绑定.py',dropped)
        installer=runpy.run_path(str(dropped))
        installer['onMayaDroppedPythonFile']();installer['onMayaDroppedPythonFile']()
        dropped.unlink()
    else:
        installer=runpy.run_path(str(ROOT/'本草角色绑定'/'安装本草角色绑定.py'))
        installer['install']();installer['install']()
    import rig_runtime_assistant as assistant
    package=assistant.ROOT.resolve()
    if single_file:
        assert package.is_relative_to(Path(c.internalVar(userAppDir=True)).resolve())
        button=c.shelfLayout('BencaoRig',q=True,childArray=True)[0]
        command=c.shelfButton(button,q=True,command=True)
        assert str(dropped) not in command
        exec(command,{})  # Shelf works after the only distributed file is removed.
    assert len(c.shelfLayout('BencaoRig',q=True,childArray=True))==1
    import maya.mel as mel
    assert '本草绑定' in c.shelfTabLayout(mel.eval('$tmp=$gShelfTopLevel'),q=True,tabLabel=True)
    # Reload the saved shelf file exactly as Maya's shelf loader does.
    shelf_path=(Path(c.internalVar(userShelfDir=True))/'shelf_BencaoRig.mel').as_posix()
    c.deleteUI('BencaoRig');c.shelfLayout('BencaoRig',parent=mel.eval('$tmp=$gShelfTopLevel'))
    mel.eval('source "'+shelf_path+'"; shelf_BencaoRig;')
    assert '本草绑定' in c.shelfTabLayout(mel.eval('$tmp=$gShelfTopLevel'),q=True,tabLabel=True)
    assert len(c.shelfLayout('BencaoRig',q=True,childArray=True))==1
    assert c.window(assistant.WINDOW,q=True,title=True)=='本草角色绑定'
    assert not c.window(assistant.WINDOW,q=True,minimizeButton=True)
    assert not c.window(assistant.WINDOW,q=True,maximizeButton=True)
    c.file(str(OUT/'character.ma'),o=True,force=True,executeScriptNodes=False)
    import maya.utils
    maya.utils.processIdleEvents()
    # File-open callbacks defer runtime preparation until the Maya event loop
    # returns. processIdleEvents alone cannot drain them inside this test call.
    from PySide2 import QtCore
    loop=QtCore.QEventLoop();QtCore.QTimer.singleShot(250,loop.quit);loop.exec_()
    assert not assistant._pending
    assert c.ls('::*.footReachRoot',objectsOnly=True),'automatic foot display activation failed'
    from maya_agent.rigs import live_edit,live_arm_manual,arm_ik,foot_space,external_constraints,native_constraints
    rig=json.loads((OUT/'rig.json').read_text(encoding='utf-8'))
    def matrix(n):return om.MMatrix(c.xform(n,q=True,ws=True,m=True))
    def diff(a,b):return max(abs(x-y) for x,y in zip(a,b))
    def poses():return {n:matrix(n) for p in rig['parts'].values() for n in p.get('joints',[])}
    initial=poses();nodes=set(c.ls(uuid=True));filter_id=id(live_edit._filter)
    for _ in range(3):assistant.enable()
    assert set(c.ls(uuid=True))==nodes and id(live_edit._filter)==filter_id
    assert max(diff(m,matrix(n)) for n,m in initial.items())<1e-8
    assistant.disable();maya.utils.processIdleEvents()
    assert not assistant._enabled and live_edit._filter is None and not arm_ik._callbacks
    assert c.button(assistant.WINDOW+'Toggle',q=True,label=True)=='已关闭'
    off=c.button(assistant.WINDOW+'Toggle',q=True,backgroundColor=True);assert off[0]>off[1]
    assistant.show();assert not assistant._enabled
    assistant.toggle();assert assistant._enabled and live_edit._filter is not None and arm_ik._callbacks
    assert c.button(assistant.WINDOW+'Toggle',q=True,label=True)=='已开启'
    on=c.button(assistant.WINDOW+'Toggle',q=True,backgroundColor=True);assert on[1]>on[0]
    c.currentTime(1);c.setToolTo('RotateSuperContext');c.autoKeyframe(state=False);arm_ik._busy=True
    gestures=[]
    for side in 'LR':
        part=rig['parts']['arm_'+side]
        for role in ('shoulder_fk','middle_fk','end_fk'):
            for axis in 'XYZ':
                c.select(part['zero_controls'][role],r=True)
                entry=live_arm_manual.begin(part['root'],role)
                try:
                    proxy=entry['proxy'];c.setAttr(proxy+'.rotate'+axis,c.getAttr(proxy+'.rotate'+axis)+11)
                    local=om.MTransformationMatrix(entry['local'])
                    local.setTranslation(om.MVector(*c.getAttr(proxy+'.translate')[0]),om.MSpace.kTransform)
                    local.setRotation(om.MEulerRotation(*[math.radians(v) for v in c.getAttr(proxy+'.rotate')[0]],c.getAttr(proxy+'.rotateOrder')))
                    expected=entry.get('input_basis',om.MMatrix())*local.asMatrix()*entry['parent']
                    live_arm_manual.update(entry,force=True)
                    err=diff(live_edit._frame(entry['source']),expected);assert err<1e-5,(side,role,axis,err)
                    gestures.append(err)
                finally:live_arm_manual.finish(entry,cancel=True)
        for mode in (1,0,1,0):
            before=poses();arm_ik.switch(part['root'],mode,key=False)
            assert max(diff(m,matrix(n)) for n,m in before.items())<1e-5
            foot_space.switch(rig['parts']['leg_'+side]['root'],mode,key=False)
    # Native constraint adapter and delete restoration use only bundled code.
    control=rig['parts']['arm_L']['zero_controls']['shoulder_fk']
    goal=c.createNode('transform',name='runtimeExternalGoal');c.xform(goal,ws=True,m=list(matrix(control)))
    before=poses();external_constraints.attach(control,goal,kind='parent',native=True)
    owner=external_constraints.registry(control);constraint=external_constraints._link(owner,'constraint')
    c.setAttr(goal+'.ry',c.getAttr(goal+'.ry')+9);c.delete(constraint);c.delete(goal)
    assert max(diff(m,matrix(n)) for n,m in before.items())<1e-5
    # Verify real undo command registration, with its module loaded from this package.
    c.undoInfo(openChunk=True,chunkName='RuntimeUndoTest')
    saved=c.getAttr(rig['master_control']+'.tx')
    snap=live_edit._snapshot([rig['master_control']+'.tx'])
    live_edit._fence('before',[snap]);c.setAttr(rig['master_control']+'.tx',saved+2)
    live_edit._fence('after',[live_edit._snapshot([rig['master_control']+'.tx'])]);c.undoInfo(closeChunk=True)
    c.undo();assert abs(c.getAttr(rig['master_control']+'.tx')-saved)<1e-8
    c.redo();assert abs(c.getAttr(rig['master_control']+'.tx')-saved-2)<1e-8
    c.undo()
    loaded={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if name.startswith('maya_agent.rigs') and getattr(module,'__file__',None)}
    assert all(Path(p).is_relative_to(package) for p in loaded.values()),loaded
    return dict(passed=True,single_file=single_file,installed_package=str(package),clean_gui=True,loaded_modules=len(loaded),gesture_cases=len(gestures),max_rotation_error=max(gestures),mode_switches=True,native_constraints=True,undo_redo=True,idempotent=True,shelf_install=True,automatic_scene_activation=True,toggle=True)


def main():
    import maya.cmds as c
    try:
        report=run()
        if os.environ.get('BENCAO_TEST_REFERENCES')=='1':
            report['references']=runpy.run_path(str(ROOT/'scripts'/'test_runtime_references.py'))['run'](OUT)
        if os.environ.get('BENCAO_TEST_KEYS')=='1':
            report['keys']=runpy.run_path(str(ROOT/'scripts'/'probe_reference_keys.py'))['run'](OUT)
        if os.environ.get('BENCAO_TEST_KEY_REGRESSION')=='1':
            report['key_regression']=runpy.run_path(str(ROOT/'scripts'/'test_reference_keying.py'))['run'](OUT)
        if os.environ.get('BENCAO_TEST_ELBOW')=='1':
            report['elbow']=runpy.run_path(str(ROOT/'scripts'/'test_elbow_absorption.py'))['run'](OUT)
        if os.environ.get('BENCAO_TEST_FOOT_REACH')=='1':
            report['foot_reach']=runpy.run_path(str(ROOT/'scripts'/'test_foot_reach.py'))['run'](OUT)
        if os.environ.get('BENCAO_TEST_FOOT_INPUT')=='1':
            report['foot_input']=runpy.run_path(str(ROOT/'scripts'/'test_foot_input_limits.py'))['run'](OUT)
            report['foot_compat']=runpy.run_path(str(ROOT/'scripts'/'test_foot_reach_compat.py'))['run'](OUT)
    except Exception:report=dict(passed=False,traceback=traceback.format_exc())
    (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if os.environ.get('BENCAO_TEST_KEEP_ALIVE')=='1':
        from PySide2 import QtCore
        request=OUT/'test-request.json'
        request.unlink(missing_ok=True)
        def poll():
            if not request.exists():return
            job=json.loads(request.read_text(encoding='utf-8'));request.unlink()
            timer.stop()
            try:
                if job.get('quit'):c.quit(force=True);return
                answer=runpy.run_path(str(ROOT/'scripts'/job['script']))['run'](OUT)
                result=dict(passed=True,data=answer)
            except Exception:result=dict(passed=False,traceback=traceback.format_exc())
            (OUT/'test-response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            timer.start(300)
        timer=QtCore.QTimer();timer.timeout.connect(poll);timer.start(300)
        globals()['_test_timer']=timer
    else:c.quit(force=True)


main()
