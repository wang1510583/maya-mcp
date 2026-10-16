"""Drop into Maya to install the portable mobile-exchange shelf button."""
from pathlib import Path
import importlib,sys
ROOT=Path(__file__).resolve().parent

def show():
    location=str(ROOT)
    if location not in sys.path:sys.path.insert(0,location)
    for name in ('maya_agent','maya_agent.rigs'):
        package=importlib.import_module(name);directory=str(ROOT.joinpath(*name.split('.')))
        package.__path__[:]=[directory]+[p for p in package.__path__ if p!=directory]
    from maya_agent.rigs.mobile_io import show_ui
    return show_ui()

def install():
    import maya.cmds as c
    import maya.mel as mel
    shelf='CustomBodyRig';top=mel.eval('$tmp=$gShelfTopLevel')
    if not c.shelfLayout(shelf,exists=True):c.shelfLayout(shelf,parent=top)
    command='import runpy\nrunpy.run_path({!r})["show"]()'.format(str(ROOT/'安装手机互通.py'))
    options=dict(label='手机动画互通',image='fileOpen.png',imageOverlayLabel='手机互通',sourceType='python',annotation='Maya 与安卓工程 / 动画导入导出',command=command)
    found=[n for n in c.shelfLayout(shelf,q=True,childArray=True) or [] if c.objectTypeUI(n)=='shelfButton' and c.shelfButton(n,q=True,label=True)=='手机动画互通']
    if found:c.shelfButton(found[0],edit=True,**options)
    else:c.shelfButton(parent=shelf,**options)
    c.shelfTabLayout(top,edit=True,selectTab=shelf);c.saveShelf(shelf,str(Path(c.internalVar(userShelfDir=True))/('shelf_'+shelf)))
    return show()

def onMayaDroppedPythonFile(*args):return install()
if __name__=='__main__':install()
