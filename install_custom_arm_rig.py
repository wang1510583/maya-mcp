"""Drag this Python file into Maya to install and open the arm-system tool."""
from pathlib import Path
import sys


def install():
    import importlib
    import maya.cmds as c
    import maya.mel as mel
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path: sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    importlib.reload(importlib.import_module('maya_agent.rigs.ui_common'))
    import maya_agent.rigs.soft_limb as arm
    importlib.reload(arm)
    for name in ('native', 'easy_rig', 'sides', 'selection', 'animation', 'ui'):
        importlib.reload(importlib.import_module('maya_agent.rigs.soft_limb.'+name))
    shelf = 'CustomBodyRig'
    top = mel.eval('$tmp=$gShelfTopLevel')
    if not c.shelfLayout(shelf, exists=True): c.shelfLayout(shelf, parent=top)
    command = ('import sys\np={0!r}\nif p not in sys.path: sys.path.insert(0,p)\n'
               'from maya_agent.rigs.soft_limb import show_ui\nshow_ui()').format(str(root))
    existing = [n for n in (c.shelfLayout(shelf,q=True,childArray=True) or [])
                if c.objectTypeUI(n)=='shelfButton' and c.shelfButton(n,q=True,label=True)=='手臂系统']
    options = dict(label='手臂系统', image='kinJoint.png', imageOverlayLabel='手臂系统',
                   annotation='选择肩、肘、腕，创建可柔化伸缩的手臂系统', sourceType='python', command=command)
    if existing: c.shelfButton(existing[0],edit=True,**options)
    else: c.shelfButton(parent=shelf,**options)
    c.shelfTabLayout(top,edit=True,selectTab=shelf)
    c.saveShelf(shelf,(Path(c.internalVar(userShelfDir=True))/('shelf_'+shelf)).as_posix())
    return arm.show_ui()


def onMayaDroppedPythonFile(*_):
    return install()


if __name__ == '__main__':
    install()
