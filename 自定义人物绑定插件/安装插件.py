"""Portable drag-and-drop installer and shelf launcher for Maya 2024."""
import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def activate():
    location = str(ROOT)
    if location in sys.path:
        sys.path.remove(location)
    sys.path.insert(0, location)
    importlib.invalidate_caches()
    for package_name in ('maya_agent', 'maya_agent.rigs', 'max_mcp'):
        package = importlib.import_module(package_name)
        directory = str(ROOT.joinpath(*package_name.split('.')))
        paths = [directory] + [path for path in package.__path__ if path != directory]
        package.__path__[:] = paths
    names = [name for name in sys.modules if name == 'maya_agent.rigs' or name.startswith('maya_agent.rigs.')
             or name in ('max_mcp.batch_client', 'max_mcp.biped_retarget', 'max_mcp.biped_keys', 'max_mcp.connection')]
    for name in names:
        module = sys.modules[name]
        directory = ROOT.joinpath(*name.split('.'))
        if hasattr(module, '__path__') and directory.is_dir():
            module.__path__[:] = [str(directory)]
    for name in sorted(names, key=lambda value: (-value.count('.'), value)):
        importlib.reload(sys.modules[name])
    for name in ('maya_agent.rigs.custom_body.definition', 'maya_agent.rigs.custom_body.builder',
                 'maya_agent.rigs.custom_body', 'maya_agent.rigs.integrated.builder', 'maya_agent.rigs.integrated'):
        importlib.reload(importlib.import_module(name))
    return ROOT


def show():
    activate()
    from maya_agent.rigs.integrated import show_ui
    return show_ui()


def install():
    import maya.cmds as cmds
    import maya.mel as mel

    activate()
    shelf = 'CustomBodyRig'
    top = mel.eval('$tmp=$gShelfTopLevel')
    if not cmds.shelfLayout(shelf, exists=True):
        cmds.shelfLayout(shelf, parent=top)
    command = 'import runpy\nrunpy.run_path({!r})["show"]()'.format(str(ROOT / '安装插件.py'))
    buttons = [node for node in cmds.shelfLayout(shelf, query=True, childArray=True) or []
               if cmds.objectTypeUI(node) == 'shelfButton'
               and cmds.shelfButton(node, query=True, label=True) == '集成角色绑定']
    options = dict(label='集成角色绑定', image='kinJoint.png', imageOverlayLabel='集成绑定',
                   sourceType='python', annotation='自定义人物绑定插件：身体、头颈、肩膀、手臂、腿部', command=command)
    if buttons:
        cmds.shelfButton(buttons[0], edit=True, **options)
    else:
        cmds.shelfButton(parent=shelf, **options)
    cmds.shelfTabLayout(top, edit=True, selectTab=shelf)
    cmds.saveShelf(shelf, (Path(cmds.internalVar(userShelfDir=True)) / ('shelf_' + shelf)).as_posix())
    from maya_agent.rigs.integrated import show_ui
    return show_ui()


def onMayaDroppedPythonFile(*args):
    return install()


if __name__ == '__main__':
    install()
