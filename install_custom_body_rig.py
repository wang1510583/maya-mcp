"""Drag into Maya to install the independent body-rig shelf button and open its UI."""
from pathlib import Path
import sys


def install():
    import importlib
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import maya.cmds as cmds
    import maya.mel as mel
    # Refresh only this module on drag/drop; keep the rest of Maya Agent intact.
    import maya_agent
    import maya_agent.rigs
    for package, directory in ((maya_agent, root/'maya_agent'), (maya_agent.rigs, root/'maya_agent/rigs')):
        location = str(directory)
        if location in package.__path__:
            package.__path__.remove(location)
        package.__path__.insert(0, location)
    importlib.invalidate_caches()
    import maya_agent.rigs.custom_body as body
    importlib.reload(body)
    for name in ('topology', 'definition', 'targets', 'fitting', 'context', 'nodes',
                 'controls', 'skeleton', 'drivers', 'display', 'builder', 'ui'):
        importlib.reload(importlib.import_module('maya_agent.rigs.custom_body.' + name))
    importlib.reload(body)
    from maya_agent.rigs.custom_body import show_ui
    top = mel.eval('$tmp=$gShelfTopLevel')
    shelf = 'CustomBodyRig'
    if not cmds.shelfLayout(shelf, exists=True):
        cmds.shelfLayout(shelf, parent=top)
    command = 'import sys\np={0!r}\nif p not in sys.path: sys.path.insert(0,p)\nfrom maya_agent.rigs.custom_body import show_ui\nshow_ui()'.format(str(root))
    existing = [child for child in (cmds.shelfLayout(shelf, query=True, childArray=True) or [])
                if cmds.objectTypeUI(child) == 'shelfButton' and cmds.shelfButton(child, query=True, label=True) == '自定义身体绑定']
    options = dict(label='自定义身体绑定', image='kinJoint.png', imageOverlayLabel='身体绑定',
                   annotation='自定义身体绑定：数量、高度及按选择顺序创建', sourceType='python', command=command)
    if existing:
        cmds.shelfButton(existing[0], edit=True, **options)
    else:
        cmds.shelfButton(parent=shelf, **options)
    cmds.shelfTabLayout(top, edit=True, selectTab=shelf)
    cmds.saveShelf(shelf, str(Path(cmds.internalVar(userShelfDir=True)) / ('shelf_' + shelf + '.mel')))
    return show_ui()


def onMayaDroppedPythonFile(*_):
    return install()


if __name__ == '__main__':
    install()
