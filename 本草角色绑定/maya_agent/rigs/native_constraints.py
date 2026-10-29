"""Maya constraint-menu adapter for this plugin's result-following controls.

Ordinary objects delegate to Maya's installed MEL implementation. The vendor
scripts are read at runtime, never edited or shipped. Creation still uses real
Maya constraint nodes; playback requires no Python evaluation.
"""
from maya_agent.rigs import scene_data
import json
import os
import re
from pathlib import Path

if '_installed' not in globals():
    _installed = False
    _watches = {}
    _scene_callbacks = []


def dispatch(kind):
    """Called only by Maya's three doCreate*ConstraintArgList procedures."""
    if globals().get('_runtime_disabled',False):return 0
    import maya.cmds as c
    import maya.mel as mel
    from . import external_constraints as external
    selected = c.ls(selection=True, long=True) or []
    if len(selected) < 2:
        return 0
    try:
        external.resolve(selected[-1])
    except ValueError:
        return 0
    version = mel.eval('global string $mayaAgentConstraintVersion; string $macVersion = $mayaAgentConstraintVersion;')
    args = mel.eval('global string $mayaAgentConstraintArgs[]; string $macArgs[] = $mayaAgentConstraintArgs;')
    if version != '1' or len(args) != (11 if kind == 'parent' else 10):
        raise ValueError('未知的 Maya 约束选项版本，未修改绑定。')
    layer = args[9 if kind == 'parent' else 8]
    if layer:
        raise ValueError('手脚外部约束请将约束选项中的动画层设为 None；原控制器动画层会保留。')
    options = dict(maintainOffset=bool(int(args[0])))
    if kind == 'parent':
        options.update(decompRotationToChild=bool(int(args[1])), weight=float(args[8]))
        for flag, start in (('skipTranslate', 2), ('skipRotate', 5)):
            axes = [axis for axis, value in zip('xyz', args[start:start+3]) if int(value)]
            if axes:
                options[flag] = axes
    else:
        options['weight'] = float(args[7])
        axes = [axis for axis, value in zip('xyz', args[4:7]) if int(value)]
        if axes:
            options['skip'] = axes
        if not options['maintainOffset']:
            options['offset'] = [float(v) for v in args[1:4]]
    external.attach(selected[-1], selected[:-1], kind, options=options, native=True)
    return 1


def _object(name):
    import maya.api.OpenMaya as om
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDependNode(0)


def _plug(name):
    import maya.api.OpenMaya as om
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getPlug(0)


def _deleting(node, modifier, *_):
    import traceback
    global _last_error
    try:
        _restore_deleted(node, modifier)
    except Exception:
        _last_error = traceback.format_exc()
        raise


def _restore_deleted(node, modifier):
    """Append restoration to Maya's own delete undo transaction.

    Never call cmds.delete/undo from this callback. Maya replays the same
    modifier for undo/redo, so restoration cannot become a separate undo step.
    """
    import maya.cmds as c
    import maya.api.OpenMaya as om
    from . import external_constraints as external
    # Two constraints below different arm controls may share a short name.
    # Resolve the actual callback object, never another same-named DAG node.
    constraint = (om.MDagPath.getAPathTo(node).fullPathName() if node.hasFn(om.MFn.kDagNode)
                  else om.MFnDependencyNode(node).name())
    owner = external.registry(constraint)
    if not owner:
        return
    source, control, matrix, anchor = (external._link(owner, a) for a in ('source', 'control', 'matrix', 'anchor'))
    if not all((source, control, matrix, anchor)):
        return
    dst = source + '.offsetParentMatrix'
    if not c.isConnected(matrix + '.matrixSum', dst):
        return  # Explicit panel removal already restored the input.
    # Preserve any user-added children beneath the temporary anchor.
    # Restoring the input is still safe; leave modified helper nodes to the user.
    disposable = not any(c.nodeType(n) in ('transform', 'joint')
                         for n in c.listRelatives(anchor, children=True) or [])
    original = c.connectionInfo(matrix + '.matrixIn[0]', sourceFromDestination=True)
    value = c.getAttr(matrix + '.matrixIn[0]')
    modifier.disconnect(_plug(matrix + '.matrixSum'), _plug(dst))
    if original:
        modifier.connect(_plug(original), _plug(dst))
    else:
        data = om.MFnMatrixData().create(om.MMatrix(value))
        modifier.newPlugValue(_plug(dst), data)
    # Flush disconnections before Maya automatically disconnects deleted nodes.
    modifier.doIt()
    if disposable:
        for n in (anchor, matrix, owner):
            modifier.deleteNode(_object(n))
        modifier.doIt()


def watch(constraint):
    import maya.api.OpenMaya as om
    handle = om.MObjectHandle(_object(constraint))
    for key, (old, callback) in list(_watches.items()):
        # Invalid but alive objects can still return through Maya's undo queue.
        if not old.isAlive():
            try:
                om.MMessage.removeCallback(callback)
            except RuntimeError:
                pass
            del _watches[key]
    key = handle.hashCode()
    if key not in _watches:
        _watches[key] = (handle, om.MNodeMessage.addNodeAboutToDeleteCallback(handle.object(), _deleting))


def refresh(*_):
    import maya.cmds as c
    from . import external_constraints as external
    for owner in c.ls('::*.' + external.DATA, objectsOnly=True) or []:
        if scene_data.read(owner + '.' + external.DATA).get('native'):
            constraint = external._link(owner, 'constraint')
            if constraint:
                watch(constraint)


def install():
    if globals().get('_runtime_disabled',False):return False
    import maya.api.OpenMaya as om
    import maya.mel as mel
    global _installed
    if not _installed:
        for kind in ('Parent', 'Point', 'Orient'):
            name = 'doCreate' + kind + 'ConstraintArgList'
            path = Path(os.environ['MAYA_LOCATION']) / 'scripts' / 'others' / (name + '.mel')
            # Preserve Maya's installed procedure under a private alias.
            source = path.read_text(encoding='utf-8')
            alias = 'mayaAgentOriginal' + kind + 'ConstraintArgList'
            saved, count = re.subn(r'(global\s+proc\s+)' + name + r'(?=\s*\()',
                                  r'\g<1>' + alias, source, count=1)
            if count != 1:
                raise RuntimeError('无法识别 Maya 原生约束入口：' + str(path))
            mel.eval(saved)
            expression = "__import__('maya_agent.rigs.native_constraints',fromlist=['dispatch']).dispatch('%s')" % kind.lower()
            mel.eval('''global proc %s(string $version, string $args[]) {
                global string $mayaAgentConstraintVersion;
                global string $mayaAgentConstraintArgs[];
                $mayaAgentConstraintVersion = $version;
                $mayaAgentConstraintArgs = $args;
                int $handled = python("%s");
                if (!$handled) %s($version, $args);
            }''' % (name, expression, alias))
        for event in (om.MSceneMessage.kAfterOpen, om.MSceneMessage.kAfterImport,
                      om.MSceneMessage.kAfterCreateReference, om.MSceneMessage.kAfterLoadReference):
            _scene_callbacks.append(om.MSceneMessage.addCallback(event, refresh))
        _installed = True
    refresh()
    return True
