"""Update existing TempoSlider windows without restarting their motion trails."""
import ast
from pathlib import Path


def run():
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    path = Path(__file__).resolve().parents[1] / '欧拉转换工具' / 'maya_speed_slider.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    version = next(ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets))
    functions = [n for n in tree.body if isinstance(n,ast.FunctionDef) and
                 (n.name.startswith('_euler_') or n.name in
                  ('calculate_euler_for_object','switch_euler_order'))]
    windows = [w for w in QtWidgets.QApplication.topLevelWidgets()
               if w.__class__.__name__ in ('TempoSlider','EulerToolWindow')]
    updated_globals, updated_methods = set(), set()
    for widget in windows:
        cls = type(widget)
        definition = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls.__name__)
        for method in definition.body:
            if not isinstance(method,ast.FunctionDef) or method.name not in (
                    'calculate_euler','switch_to_best_euler','switch_euler'):
                continue
            existing = getattr(cls,method.name)
            namespace = existing.__globals__
            if id(namespace) not in updated_globals:
                exec(compile(ast.Module(body=functions,type_ignores=[]),str(path),'exec'),namespace)
                namespace['__version__']=version
                updated_globals.add(id(namespace))
            if id(existing) not in updated_methods:
                scratch={}
                exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),scratch)
                # Existing Qt signal slots retain this function object.
                existing.__code__=scratch[method.name].__code__
                updated_methods.add(id(existing))
        if hasattr(widget,'switch_btn'):
            widget.switch_btn.setToolTip('保留全部原关键帧姿态（含小数帧）；帧间插值可能变化。支持一次撤销。')
    return dict(windows=len(windows),methods=len(updated_methods),version=version,file=str(path))
