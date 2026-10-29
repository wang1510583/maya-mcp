"""Drag into Maya once; the shelf opens the small runtime assistant."""
from pathlib import Path
import importlib
import sys

ROOT=Path(__file__).resolve().parent


def show():
    existing=sys.modules.get('rig_runtime_assistant')
    if existing and Path(existing.__file__).resolve().parent!=ROOT:
        raise RuntimeError('已从另一位置启用运行助手，请重启 Maya 后再从新位置安装。')
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    importlib.invalidate_caches()
    return importlib.import_module('rig_runtime_assistant').show()


def install():
    import maya.cmds as c
    import maya.mel as mel
    # Verify launch before persisting a shelf entry.
    window=show()
    shelf='BencaoRig';top=mel.eval('$tmp=$gShelfTopLevel')
    if not c.shelfLayout(shelf,exists=True):c.shelfLayout(shelf,parent=top)
    c.shelfTabLayout(top,e=True,tabLabel=(shelf,'本草绑定'))
    command='import runpy\nrunpy.run_path({!r})["show"]()'.format(str(ROOT/'安装本草角色绑定.py'))
    buttons=[n for n in c.shelfLayout(shelf,q=True,childArray=True) or []
             if c.objectTypeUI(n)=='shelfButton' and c.shelfButton(n,q=True,label=True)=='本草角色绑定']
    options=dict(label='本草角色绑定',image='kinJoint.png',imageOverlayLabel='本草绑定',sourceType='python',command=command,
                 annotation='打开本草角色绑定')
    if buttons:c.shelfButton(buttons[0],e=True,**options)
    else:c.shelfButton(parent=shelf,**options)
    c.shelfTabLayout(top,e=True,selectTab=shelf)
    shelf_file=Path(c.internalVar(userShelfDir=True))/('shelf_'+shelf+'.mel')
    c.saveShelf(shelf,shelf_file.with_suffix('').as_posix())
    # Reapply the Chinese display name when Maya reloads this saved shelf.
    encoding='mbcs' if sys.platform=='win32' else 'utf-8'
    text=shelf_file.read_text(encoding=encoding)
    end=text.rfind('}')
    text=text[:end]+'\n    global string $gShelfTopLevel;\n    shelfTabLayout -e -tabLabel "BencaoRig" "本草绑定" $gShelfTopLevel;\n'+text[end:]
    shelf_file.write_text(text,encoding=encoding)
    return window


def onMayaDroppedPythonFile(*args):return install()


if __name__=='__main__':install()
