"""Small animator-facing launcher; never rebuilds, migrates or saves a rig."""
import hashlib
import importlib
import json
from pathlib import Path
import sys

VERSION='1.0.6'
ROOT=Path(__file__).resolve().parent
WINDOW='BencaoCharacterRig'
_callbacks=globals().get('_callbacks',[])
_pending=False
_status=None
_enabled=globals().get('_enabled',False)


def activate_package():
    """Reuse identical loaded code; never hot-swap active gesture callbacks."""
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    integrated=sys.modules.get('maya_agent.rigs.integrated')
    if integrated and integrated.VERSION!=manifest['source_version']:
        raise RuntimeError('已加载另一版本的角色绑定，请保存工作并重启 Maya 后再启用。')
    records={r['path']:r for r in manifest['files']}
    for name,module in list(sys.modules.items()):
        if not name.startswith('maya_agent.rigs.'):continue
        path=getattr(module,'__file__',None)
        relative=name.replace('.','/')+('/__init__.py' if hasattr(module,'__path__') else '.py')
        if not path or relative not in records:continue
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=records[relative]['sha256']:
            raise RuntimeError('当前 Maya 已加载另一版本的绑定组件。请保存工作并重启 Maya，再启用本助手，避免混用版本。')
    location=str(ROOT)
    if location not in sys.path:sys.path.insert(0,location)
    importlib.invalidate_caches()
    package=importlib.import_module('maya_agent')
    if 'maya_agent.rigs' not in sys.modules:
        bundled=str(ROOT/'maya_agent')
        package.__path__[:]=[bundled]+[p for p in package.__path__ if p!=bundled]
    return manifest


def enable(*args):
    import maya.cmds as c
    manifest=activate_package()
    from maya_agent.rigs import live_edit,arm_ik,native_constraints,zero_manual,switch_panel,wrist_key_colors,key_companions
    if c.about(batch=True):raise RuntimeError('请在 Maya 图形界面中启用角色控制。')
    for module in (live_edit,arm_ik,native_constraints,zero_manual,switch_panel,wrist_key_colors,key_companions):module._runtime_disabled=False
    live_edit.install()
    arm_ik.install()
    install_scene_callbacks()
    roots=[n for n in c.ls(type='transform',long=True) or []
           if c.attributeQuery('integratedRigData',node=n,exists=True)]
    status='已启用 · 检测到 {} 套集成角色\n运行核心 {} · 助手 {}'.format(len(roots),manifest['source_version'],VERSION)
    if not roots:status+='\n打开角色文件后会自动接入。'
    global _status,_enabled
    _status=status
    _enabled=True
    _update_button()
    return dict(enabled=True,characters=len(roots),source_version=manifest['source_version'])


def _enable_safe(*args):
    import maya.cmds as c
    try:return enable()
    except Exception as exc:
        message=str(exc) or type(exc).__name__
        c.warning(message)


def _update_button():
    import maya.cmds as c
    if c.button(WINDOW+'Toggle',exists=True):
        c.button(WINDOW+'Toggle',e=True,label='已开启' if _enabled else '已关闭',
                 backgroundColor=(.18,.52,.26) if _enabled else (.68,.18,.18),enableBackground=True)


def disable():
    import maya.api.OpenMaya as om
    from maya_agent.rigs import live_edit,arm_ik,native_constraints,zero_manual,switch_panel,wrist_key_colors,key_companions
    if live_edit._gesture or arm_ik._pending or switch_panel._pending or zero_manual._session or key_companions._session:
        raise RuntimeError('请结束当前控制器操作后再关闭。')
    for module in (live_edit,arm_ik,native_constraints,zero_manual,switch_panel,wrist_key_colors,key_companions):module._runtime_disabled=True
    key_companions.uninstall()
    if getattr(live_edit,'_filter',None) is not None:
        from PySide2 import QtWidgets
        QtWidgets.QApplication.instance().removeEventFilter(live_edit._filter)
        live_edit._filter.deleteLater();live_edit._filter=None
    for module in (arm_ik,switch_panel):
        for entry in module._callbacks.values():
            try:om.MMessage.removeCallback(entry['id'])
            except RuntimeError:pass
        module._callbacks.clear()
    for callback in arm_ik._scene_callbacks:
        try:om.MMessage.removeCallback(callback)
        except RuntimeError:pass
    arm_ik._scene_callbacks[:]=[]
    if zero_manual._callback is not None:
        om.MMessage.removeCallback(zero_manual._callback);zero_manual._callback=None
    wrist_key_colors.uninstall()
    # Keep existing constraint-delete restoration and the undo command alive:
    # turning the assistant off must not corrupt existing constraints or history.
    global _enabled
    _enabled=False
    _update_button()
    return dict(enabled=False)


def toggle(*args):
    import maya.cmds as c
    try:return disable() if _enabled else enable()
    except Exception as exc:c.warning(str(exc) or type(exc).__name__)


def install_scene_callbacks():
    import maya.api.OpenMaya as om
    if _callbacks:return
    def changed(*args):
        global _pending
        if _pending:return
        _pending=True
        import maya.utils
        def deferred():
            global _pending
            _pending=False
            if _enabled:_enable_safe()
        maya.utils.executeDeferred(deferred)
    for event in (om.MSceneMessage.kAfterOpen,om.MSceneMessage.kAfterImport,
                  om.MSceneMessage.kAfterCreateReference,om.MSceneMessage.kAfterLoadReference,
                  om.MSceneMessage.kAfterUnloadReference,om.MSceneMessage.kAfterRemoveReference):
        _callbacks.append(om.MSceneMessage.addCallback(event,changed))


def show():
    import maya.cmds as c
    if c.window(WINDOW,exists=True):c.deleteUI(WINDOW)
    c.window(WINDOW,title='本草角色绑定',widthHeight=(180,60),sizeable=False,minimizeButton=False,maximizeButton=False)
    c.columnLayout(adjustableColumn=True,columnAttach=('both',8),rowSpacing=6)
    c.button(WINDOW+'Toggle',label='已开启' if _enabled else '已关闭',height=42,command=toggle)
    c.showWindow(WINDOW)
    if _status is None:_enable_safe()
    _update_button()
    return WINDOW
