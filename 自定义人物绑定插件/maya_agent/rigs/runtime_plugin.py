"""Load the undo command from an ASCII path for Maya's Windows plug-in loader."""
import hashlib
import tempfile
from pathlib import Path


def ascii_plugin_path(source, roots):
    source=Path(source).resolve()
    content=source.read_bytes()
    # This small command plug-in is packaged with the rig; never downloaded.
    content.decode('utf-8')
    if str(source).isascii():return source
    digest=hashlib.sha256(content).hexdigest()[:16]
    errors=[]
    for root in roots:
        if not root:continue
        destination=Path(root)/'integrated_rig_runtime'/digest/source.name
        if not str(destination).isascii():continue
        try:
            destination.parent.mkdir(parents=True,exist_ok=True)
            if not destination.exists() or destination.read_bytes()!=content:
                with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False,suffix='.tmp') as stream:
                    stream.write(content);temporary=Path(stream.name)
                try:temporary.replace(destination)
                finally:temporary.unlink(missing_ok=True)
            if destination.read_bytes()!=content:raise RuntimeError('Undo plugin cache verification failed')
            return destination
        except OSError as exc:errors.append(str(exc))
    raise RuntimeError('无法找到可写的纯英文插件缓存路径：'+'; '.join(errors))


def ensure_undo_command():
    import maya.cmds as c
    if callable(getattr(c,'mayaLiveEditState',None)):return True
    source=Path(__file__).with_name('maya_live_edit_undo.py')
    plugin=ascii_plugin_path(source,[Path(c.internalVar(userAppDir=True))/'plug-ins',tempfile.gettempdir()])
    c.loadPlugin(str(plugin).replace('\\','/'),quiet=True)
    # Maya can print a Python loader error and return without raising. Check
    # the actual command before allowing a binding/gesture to modify a scene.
    if not callable(getattr(c,'mayaLiveEditState',None)):
        raise RuntimeError('撤销辅助插件未能注册 mayaLiveEditState，未继续创建绑定。插件路径：'+str(plugin))
    return True
