import importlib.util
from pathlib import Path
import pytest

path=Path(__file__).resolve().parents[1]/'自定义人物绑定插件/maya_agent/rigs/runtime_plugin.py'
spec=importlib.util.spec_from_file_location('rig_runtime_plugin',path)
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


def test_unicode_source_is_copied_and_verified(tmp_path):
    source=tmp_path/'中文插件'/'maya_live_edit_undo.py';source.parent.mkdir();source.write_bytes(b'# trusted plugin\n')
    result=runtime.ascii_plugin_path(source,[tmp_path/'中文缓存',tmp_path/'ascii'])
    assert str(result).isascii() and result.read_bytes()==source.read_bytes()
    assert runtime.ascii_plugin_path(source,[tmp_path/'ascii'])==result
    result.write_bytes(b'# stale\n')
    assert runtime.ascii_plugin_path(source,[tmp_path/'ascii']).read_bytes()==source.read_bytes()


def test_ascii_source_uses_original(tmp_path):
    source=tmp_path/'plugin.py';source.write_bytes(b'# plugin\n')
    assert runtime.ascii_plugin_path(source,[])==source.resolve()


def test_no_ascii_writable_path_fails_before_loading(tmp_path):
    source=tmp_path/'中文'/'plugin.py';source.parent.mkdir();source.write_bytes(b'# plugin\n')
    with pytest.raises(RuntimeError):runtime.ascii_plugin_path(source,[tmp_path/'中文缓存'])
