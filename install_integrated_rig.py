"""Drag into Maya to install the diagram-based integrated character rig panel."""
import sys
from pathlib import Path


def install():
    import importlib
    import maya.cmds as c
    import maya.mel as mel
    root=Path(__file__).resolve().parent
    if str(root) not in sys.path:sys.path.insert(0,str(root))
    importlib.invalidate_caches()
    for module in ('maya_agent.rigs.custom_body.topology','maya_agent.rigs.custom_body.definition',
                   'maya_agent.rigs.custom_body.builder','maya_agent.rigs.custom_body',
                   'maya_agent.rigs.custom_body.targets','maya_agent.rigs.custom_body.ui','maya_agent.rigs.soft_limb',
                   'maya_agent.rigs.soft_limb.easy_rig','maya_agent.rigs.soft_limb.ui','maya_agent.rigs.soft_leg.ui',
                   'maya_agent.rigs.integrated','maya_agent.rigs.head_neck','maya_agent.rigs.head_neck.ui',
                   'maya_agent.rigs.integrated.shoulder','maya_agent.rigs.integrated.spaces','maya_agent.rigs.integrated.attachments','maya_agent.rigs.integrated.hierarchy',
                   'maya_agent.rigs.integrated.shoulder_ui','maya_agent.rigs.integrated.display','maya_agent.rigs.integrated.builder','maya_agent.rigs.integrated.ui'):
        importlib.reload(importlib.import_module(module))
    shelf='CustomBodyRig';top=mel.eval('$tmp=$gShelfTopLevel')
    if not c.shelfLayout(shelf,exists=True):c.shelfLayout(shelf,parent=top)
    command=('import sys\np={0!r}\nif p not in sys.path:sys.path.insert(0,p)\n'
             'from maya_agent.rigs.integrated import show_ui\nshow_ui()').format(str(root))
    buttons=[n for n in c.shelfLayout(shelf,q=True,childArray=True) or []
             if c.objectTypeUI(n)=='shelfButton' and c.shelfButton(n,q=True,label=True)=='集成角色绑定']
    opts=dict(label='集成角色绑定',image='kinJoint.png',imageOverlayLabel='集成绑定',sourceType='python',
              annotation='左键载入、右键设置、中键清空；参考层级连接及独立头颈系统',command=command)
    if buttons:c.shelfButton(buttons[0],e=True,**opts)
    else:c.shelfButton(parent=shelf,**opts)
    c.shelfTabLayout(top,e=True,selectTab=shelf)
    c.saveShelf(shelf,(Path(c.internalVar(userShelfDir=True))/('shelf_'+shelf)).as_posix())
    from maya_agent.rigs.integrated import show_ui
    return show_ui()


def onMayaDroppedPythonFile(*_):return install()
if __name__=='__main__':install()
