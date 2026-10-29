"""Reproduce native S keying after direct edits and runtime gestures."""
import json


def run(out):
    import maya.cmds as c
    import maya.mel as mel
    import maya.utils
    from PySide2 import QtCore
    from maya_agent.rigs import scene_data, live_edit
    import rig_runtime_assistant as assistant
    source=json.loads((out/'rig.json').read_text(encoding='utf-8'))
    config=json.loads((out/'key-probe-config.json').read_text(encoding='utf-8')) if (out/'key-probe-config.json').exists() else {}
    fixture=out/config.get('file','character.ma')
    source['root']=config.get('root',source['root'])
    reports=[]
    def pose(rig):return {n:c.xform(n,q=True,ws=True,m=True) for p in rig['parts'].values() for n in p.get('joints',[])}
    def error(before):return max([abs(a-b) for n,m in before.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))] or [0])
    for referenced in config.get('references',(False,True)):
        for method in ('direct','gesture'):
            for part,role in (('head','head'),('arm_L','shoulder_fk'),('arm_L','end_fk'),('leg_L','foot')):
                c.file(new=True,force=True)
                if referenced:
                    c.file(str(fixture),reference=True,namespace='keyTest',executeScriptNodes=False)
                    root='keyTest:'+source['root']
                else:
                    c.file(str(fixture),open=True,force=True,executeScriptNodes=False)
                    root=source['root']
                maya.utils.processIdleEvents();assistant.enable()
                if config.get('repair'):
                    import importlib.util,sys
                    path=out.parents[1]/'自定义人物绑定插件/maya_agent/rigs/reference_animation.py'
                    spec=importlib.util.spec_from_file_location('maya_agent.rigs.reference_animation',path)
                    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
                    module.prepare()
                rig=scene_data.read(root+'.integratedRigData')
                ctrl=rig['parts'][part]['zero_controls'][role]
                c.currentTime(3);c.autoKeyframe(state=False);c.setToolTo('RotateSuperContext');c.select(ctrl,r=True)
                maya.utils.processIdleEvents()
                if method=='gesture':live_edit.before_drag('manipRotate')
                c.setAttr(ctrl+'.rotateY',c.getAttr(ctrl+'.rotateY')+13)
                if method=='gesture':live_edit.update_drag(force=True);live_edit.after_drag('manipRotate')
                before=pose(rig);value=c.getAttr(ctrl+'.rotate')[0]
                mel.eval(c.runTimeCommand('SetKey',q=True,command=True))
                after=c.getAttr(ctrl+'.rotate')[0];immediate=error(before)
                maya.utils.processIdleEvents()
                loop=QtCore.QEventLoop();QtCore.QTimer.singleShot(150,loop.quit);loop.exec_()
                maya.utils.processIdleEvents()
                idle=error(before)
                c.currentTime(4);c.currentTime(3);maya.utils.processIdleEvents()
                reports.append(dict(referenced=referenced,method=method,part=part,role=role,
                                    before=value,after=after,returned=c.getAttr(ctrl+'.rotate')[0],
                                    immediate_error=immediate,idle_error=idle,return_error=error(before)))
                (out/config.get('report','key-probe.json')).write_text(json.dumps(reports,indent=2),encoding='utf-8')
    return reports
