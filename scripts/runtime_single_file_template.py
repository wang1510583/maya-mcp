# -*- coding: utf-8 -*-
"""本草角色绑定：将本文件拖入 Maya，即可安装并打开。无需解压。"""
import base64
import hashlib
import io
from pathlib import Path
import runpy
import tempfile
from zipfile import ZipFile

_SHA256 = '__ARCHIVE_SHA256__'
_PAYLOAD = b'''__ARCHIVE_BASE64__'''


def _install_files():
    import maya.cmds as cmds
    archive = base64.b64decode(_PAYLOAD, validate=False)
    if hashlib.sha256(archive).hexdigest() != _SHA256:
        raise RuntimeError('本草角色绑定安装文件不完整，请重新复制此文件。')
    base = Path(cmds.internalVar(userAppDir=True)) / 'BencaoRig' / 'runtime'
    base.mkdir(parents=True, exist_ok=True)
    target = base / _SHA256
    with ZipFile(io.BytesIO(archive)) as bundle:
        files = {}
        for entry in bundle.infolist():
            parts = entry.filename.split('/')
            if parts[0] != '本草角色绑定' or len(parts) < 2:
                raise RuntimeError('安装包路径无效。')
            relative = Path(*parts[1:])
            if relative.is_absolute() or any(p in ('', '.', '..') or ':' in p or '\\' in p for p in parts[1:]):
                raise RuntimeError('安装包路径无效。')
            files[relative] = bundle.read(entry)
    if target.exists():
        # Never overwrite code that a running Maya session may have loaded.
        for relative, content in files.items():
            path = target / relative
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError('已安装组件不完整。请关闭 Maya，删除 {} 后重新拖入安装。'.format(target))
        return target
    with tempfile.TemporaryDirectory(prefix='install-', dir=str(base)) as temporary:
        staged = Path(temporary) / 'package'
        staged.mkdir()
        for relative, content in files.items():
            path = staged / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        staged.rename(target)
    return target


def install():
    installed = _install_files()
    return runpy.run_path(str(installed / '安装本草角色绑定.py'))['install']()


def onMayaDroppedPythonFile(*args):
    return install()


if __name__ == '__main__':
    install()
