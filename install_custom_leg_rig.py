"""Drag into Maya to install the independent leg-system shelf tool."""
from pathlib import Path
import sys


def install():
    import importlib
    import maya.cmds as c
    import maya.mel as mel
    root=Path(__file__).resolve().parent
    if str(root) not in sys.path:sys.path.insert(0,str(root))
    importlib.invalidate_caches()
    importlib.reload(importlib.import_module('maya_agent.rigs.ui_common'))
    for name in ('maya_agent.rigs.soft_limb.native','maya_agent.rigs.soft_limb.sides','maya_agent.rigs.soft_leg',
                 'maya_agent.rigs.soft_leg.pivot_animation','maya_agent.rigs.soft_leg.adjustment','maya_agent.rigs.soft_leg.selection',
                 'maya_agent.rigs.soft_leg.animation','maya_agent.rigs.soft_leg.ui'):
        importlib.reload(importlib.import_module(name))
    shelf='CustomBodyRig'
    top=mel.eval('$tmp=$gShelfTopLevel')
    if not c.shelfLayout(shelf,exists=True):c.shelfLayout(shelf,parent=top)
    command=('import sys\np={0!r}\nif p not in sys.path:sys.path.insert(0,p)\n'
             'from maya_agent.rigs.soft_leg import show_ui\nshow_ui()').format(str(root))
    existing=[n for n in c.shelfLayout(shelf,q=True,childArray=True) or []
              if c.objectTypeUI(n)=='shelfButton' and c.shelfButton(n,q=True,label=True)=='腿部系统']
    options=dict(label='腿部系统',image='kinJoint.png',imageOverlayLabel='腿部系统',
                 annotation='四点腿部绑定及脚跟脚尖支点调整模式',sourceType='python',command=command)
    if existing:c.shelfButton(existing[0],e=True,**options)
    else:c.shelfButton(parent=shelf,**options)
    c.shelfTabLayout(top,e=True,selectTab=shelf)
    c.saveShelf(shelf,(Path(c.internalVar(userShelfDir=True))/('shelf_'+shelf)).as_posix())
    from maya_agent.rigs.soft_leg import show_ui
    return show_ui()


def onMayaDroppedPythonFile(*_):return install()


if __name__=='__main__':install()
