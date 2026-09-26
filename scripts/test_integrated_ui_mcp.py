"""Actual Qt mouse input plus Maya native detail callbacks and cross-request undo."""
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request


def py(code):return request('python',{'code':code})['result']


def main():
    prefix='_integratedUI_'+uuid.uuid4().hex[:7]
    snap=py("result={'nodes':cmds.ls(long=True),'selection':cmds.ls(sl=True,long=True) or [],'time':cmds.currentTime(q=True),'auto':cmds.autoKeyframe(q=True,state=True)}")
    ui_snapshot=py("import copy\nfrom maya_agent.rigs.integrated import ui\nresult={'parts':copy.deepcopy(ui._state),'root':copy.deepcopy(ui._root_state),'name':ui._instance.namespace.text() if ui._instance else 'customCharacter'}")
    rig=None;fixture=None
    try:
        fixture=py('prefix='+repr(prefix)+'''
import runpy,copy
from maya_agent.rigs.integrated import ui
from PySide2 import QtCore,QtTest,QtWidgets
suite=runpy.run_path('D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/test_integrated_rig_live.py')
cmds.autoKeyframe(state=False)
root,parts=suite['fixture'](prefix,True,shoulders=True);cmds.currentTime(1)
w=ui._instance or ui.show()
w.clear();w.namespace.setText(prefix)
ui._state['leg_L']['connected']=True
for key in ('head','body','shoulder_R','arm_R','leg_L'):
 cmds.select(clear=True)
 for node in parts[key]['targets']:cmds.select(node,add=True)
 QtTest.QTest.mouseClick(w.diagram.buttons[key],QtCore.Qt.LeftButton)
 assert len(ui._state[key]['uuids'])==len(parts[key]['targets']),(key,'load',w.status.text())
 assert '已载入' in w.diagram.buttons[key].text(),(key,'badge')
 QtTest.QTest.mouseClick(w.diagram.buttons[key],QtCore.Qt.RightButton)
 d=w.details_windows[key]
 if key in ('arm_R','leg_L'):
  assert not cmds.checkBox(d.right_side,q=True,visible=True),(key,'visible')
  assert not cmds.checkBox(d.right_side,q=True,manage=True),(key,'manage')
 cmds.checkBox(d.copy_animation,e=True,value=True);d.toggle_animation()
 cmds.floatFieldGrp(d.frame_bounds,e=True,value1=1,value2=5)
 cmds.floatFieldGrp(d.sample_step,e=True,value1=1)
 for option,field in d.space_fields.items():cmds.checkBox(field,e=True,value=True)
 from maya import OpenMayaUI
 from shiboken2 import wrapInstance
 native=wrapInstance(int(OpenMayaUI.MQtUtil.findControl(d.create_button)),QtWidgets.QPushButton)
 native.click()
 assert ui._state[key]['copy_animation'],(key,'save',w.status.text())
 assert all(ui._state[key][opt] for opt in d.space_fields),(key,'space settings')
 # Middle click clears only the load; nodes, selection and saved options survive.
 selection=cmds.ls(sl=True,long=True) or []
 QtTest.QTest.mouseClick(w.diagram.buttons[key],QtCore.Qt.MiddleButton)
 assert not ui._state[key]['uuids'] and not ui._state[key]['targets'],(key,'middle clear')
 assert '未载入' in w.diagram.buttons[key].text()
 assert all(cmds.objExists(n) for n in parts[key]['targets'])
 assert (cmds.ls(sl=True,long=True) or [])==selection
 assert ui._state[key]['copy_animation']
 QtTest.QTest.mouseClick(w.diagram.buttons[key],QtCore.Qt.LeftButton)
 assert len(ui._state[key]['uuids'])==len(parts[key]['targets'])
QtWidgets.QApplication.processEvents()
w.diagram.grab()
a,b=w.diagram.lines['leg_L'];pos=((a+b)*.5).toPoint()
QtTest.QTest.mouseClick(w.diagram,QtCore.Qt.LeftButton,pos=pos)
assert not ui._state['leg_L']['connected'],('toggle',a.x(),a.y(),b.x(),b.y())
cmds.select(root,r=True);w.root_button.click()
assert ui._root_state['uuid'],'root uuid'
assert '已载入' in w.root_button.text(),'root badge'
QtTest.QTest.mouseClick(w.root_button,QtCore.Qt.MiddleButton)
assert not ui._root_state['uuid'],'root middle clear'
w.root_button.click()
result={'root':root,'targets':sum([p['targets'] for p in parts.values()],[]),'parts':parts}
''')
        # Save a comparison on source animation, including unselected parts.
        motion=py('old=cmds.currentTime(q=True)\nresult={}\nfor f in [1,3,5]:\n cmds.currentTime(f)\n result[str(f)]={n:cmds.xform(n,q=True,ws=True,m=True) for n in '+repr(fixture['targets'])+'}\ncmds.currentTime(old)')
        rig=py('from maya_agent.rigs.integrated import ui\nresult=ui._instance.create()')
        assert set(rig['parts'])=={'head','body','shoulder_R','arm_R','leg_L'}
        assert rig['general_root']==fixture['root'] or rig['general_root']=='|'+fixture['root']
        assert rig['parts']['body']['attachment']['parent']==rig['general_root']
        assert rig['parts']['arm_R']['side']=='R'
        assert not rig['parts']['leg_L']['connected']
        request('undo',{'expected_chunk':'MayaMCP_Python'})
        py('assert not cmds.objExists('+repr(rig['root'])+')\nresult=True')
        py('old=cmds.currentTime(q=True)\nfor f,poses in '+repr(motion)+'.items():\n cmds.currentTime(float(f))\n for n,m in poses.items():\n  assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-4,(n,f)\ncmds.currentTime(old)\nresult=True')
        py('cmds.redo()\nresult=True')
        py('assert cmds.objExists('+repr(rig['root'])+')\nold=cmds.currentTime(q=True)\nfor f,poses in '+repr(motion)+'.items():\n cmds.currentTime(float(f))\n for n,m in poses.items():\n  assert max(abs(a-b) for a,b in zip(cmds.xform(n,q=True,ws=True,m=True),m))<1e-4,(n,f)\ncmds.currentTime(old)\nresult=True')
        result=dict(passed=True,left_click_load=True,right_click_settings=True,no_RL_checkbox=True,
                    clickable_connections=True,general_root_loading=True,unloaded_skipped=True,
                    body_under_general_root=True,middle_click_clear=True,undo_source_animation=True,redo_animation=True)
    finally:
        code='import runpy\nsuite=runpy.run_path("D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/test_integrated_rig_live.py")\n'
        if rig:code+='suite["remove"]('+repr(rig)+')\n'
        code+='before=set('+repr(snap['nodes'])+')\n'
        code+='for n in sorted(set(cmds.ls(long=True))-before,key=lambda n:n.count("|"),reverse=True):\n if cmds.objExists(n):cmds.delete(n)\n'
        code+='cmds.currentTime('+repr(snap['time'])+')\ncmds.autoKeyframe(state='+repr(snap['auto'])+')\n'
        code+='cmds.select('+repr(snap['selection'])+',r=True) if '+repr(bool(snap['selection']))+' else cmds.select(clear=True)\n'
        code+='from maya_agent.rigs.integrated import ui\nw=ui._instance\n'
        code+='ui._state.clear();ui._state.update('+repr(ui_snapshot['parts'])+')\n'
        code+='ui._root_state.clear();ui._root_state.update('+repr(ui_snapshot['root'])+')\n'
        code+='w.namespace.setText('+repr(ui_snapshot['name'])+');w.diagram.refresh();w.refresh_root();w.message("界面检查完成。")\n'
        code+='assert set(cmds.ls(long=True))==before\nresult=True'
        py(code)
    (ROOT/'outputs/integrated-rig-tests/ui.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
