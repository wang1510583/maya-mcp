"""File-based BIP conversion in an isolated Max process; no socket or MCP server."""
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def installations():
    """Return installed batch executables, oldest supported version first."""
    found = set()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Autodesk\3dsMax',
                           0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                version = winreg.EnumKey(key, index)
                try:
                    with winreg.OpenKey(key, version) as child:
                        directory = winreg.QueryValueEx(child, 'Installdir')[0]
                    exe = Path(directory) / '3dsmaxbatch.exe'
                    if exe.is_file(): found.add(str(exe))
                except OSError:
                    continue
    except (ImportError, OSError):
        pass
    return sorted(found)


def find_executable(executable=None):
    candidates = [executable] if executable else installations()
    if not candidates:
        raise ValueError('未找到后台 Max。请安装并激活 3ds Max，或指定 3dsmaxbatch.exe。')
    path = Path(candidates[0]).expanduser().resolve()
    if path.name.lower() != '3dsmaxbatch.exe' or not path.is_file():
        raise ValueError('后台程序不存在或不是 3dsmaxbatch.exe：' + str(path))
    return path


def _stop(process):
    if process.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    else:
        process.kill()
    process.wait(timeout=20)


def _environment(exe, directory):
    # Maya prepends its own DLLs (notably Arnold) to PATH. Inheriting those
    # makes otherwise successful Max jobs fail to load Max's renderer plugins.
    env = os.environ.copy()
    maya_roots = [env.get('MAYA_LOCATION', '')]
    host = Path(sys.executable)
    if host.stem.lower() in ('maya', 'mayapy', 'mayabatch'):
        maya_roots.append(str(host.parent.parent))
    def normalized(path): return os.path.normcase(os.path.abspath(path.strip('"')))
    maya_roots = [normalized(p) for p in maya_roots if p]
    paths = []
    for value in env.get('PATH', '').split(os.pathsep):
        if not value: continue
        current = normalized(value)
        if any(current == root or current.startswith(root + os.sep) for root in maya_roots): continue
        # Maya modules can be installed outside MAYA_LOCATION (Arnold, Bifrost,
        # MayaUSD, Substance). Their DLL directories must also be excluded.
        if any('mtoa' in part.lower() or 'for maya' in part.lower() or
               re.fullmatch(r'maya(?:\d{4}|usd)?', part, re.IGNORECASE)
               for part in Path(value).parts): continue
        paths.append(value)
    env['PATH'] = os.pathsep.join([str(exe.parent)] + paths)
    for name in list(env):
        if name.upper().startswith(('MAYA_', 'MTOA_', 'ARNOLD_', 'QT_', 'PYSIDE_')) or name.upper() in (
                'PYTHONHOME', 'PYTHONPATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH'):
            env.pop(name, None)
    env['MAYA_BIP_BATCH_JOB'] = str(directory)
    return env


def _launch(args, **options):
    """Prevent Maya's SetDllDirectory (inherited by children) leaking to Max.

    Windows PATH isolation alone cannot fix this. Restore Maya's process setting
    immediately after CreateProcess, before pumping any Maya/Qt events.
    """
    if os.name != 'nt': return subprocess.Popen(args, **options)
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_directory = kernel.GetDllDirectoryW
    get_directory.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    get_directory.restype = ctypes.c_uint32
    set_directory = kernel.SetDllDirectoryW
    set_directory.argtypes = [ctypes.c_wchar_p]
    set_directory.restype = ctypes.c_int
    length = get_directory(0, None)
    if not length: return subprocess.Popen(args, **options)
    buffer = ctypes.create_unicode_buffer(length + 1)
    get_directory(len(buffer), buffer)
    if not set_directory(None): raise ctypes.WinError(ctypes.get_last_error())
    try:
        return subprocess.Popen(args, **options)
    finally:
        if not set_directory(buffer.value): raise ctypes.WinError(ctypes.get_last_error())


def capture(params, executable=None, timeout=600, progress=None, fps=30):
    """progress(elapsed_seconds) may return False to cancel before Maya is edited.

    Successful jobs are removed; failed jobs retain request and logs for diagnosis.
    Only the process started by this call is ever stopped.
    """
    from .biped_retarget import validate_profile
    params = dict(params)
    path = Path(params.get('bip_path') or '').expanduser().resolve()
    if path.suffix.lower() != '.bip' or not path.is_file():
        raise ValueError('请选择已保存的 .bip 动画文件；后台导入不需要开启 MCP。')
    validate_profile(params['profile'])
    step = float(params.get('step', .5))
    if not math.isfinite(step) or step <= 0: raise ValueError('采样间隔必须大于 0。')
    start, end = params.get('start'), params.get('end')
    if any(v is not None and not math.isfinite(float(v)) for v in (start, end)):
        raise ValueError('帧范围必须为有限数值。')
    if start is not None and end is not None and end < start: raise ValueError('结束帧不能小于起始帧。')
    if not math.isfinite(float(timeout)) or timeout <= 0: raise ValueError('超时时间必须大于 0。')
    if not 1 <= int(fps) <= 4800 or int(fps) != fps: raise ValueError('Max 帧率必须是 1–4800 的整数。')
    exe = find_executable(executable)
    params['bip_path'] = str(path)
    params['step'] = step
    directory = Path(tempfile.mkdtemp(prefix='maya_bip_batch_'))
    request = directory / 'request.json'
    request.write_text(json.dumps(dict(params=params, fps=int(fps)), ensure_ascii=False), encoding='utf-8')
    result_path = directory / 'result.json'
    env = _environment(exe, directory)
    args = [str(exe), str(Path(__file__).with_name('batch_worker.py')),
            '-v', '2', '-dm', 'on', '-log', str(directory / 'max.log'),
            '-listenerlog', str(directory / 'listener.log')]
    options = dict(env=env, cwd=str(exe.parent))
    if os.name == 'nt': options['creationflags'] = subprocess.CREATE_NO_WINDOW
    process = None
    success = False
    try:
        with (directory / 'batch.log').open('wb') as log:
            process = _launch(args, stdout=log, stderr=subprocess.STDOUT, **options)
            began = time.monotonic()
            while process.poll() is None:
                elapsed = time.monotonic() - began
                if progress is not None and progress(elapsed) is False:
                    raise RuntimeError('已取消后台 BIP 转换，尚未写入 Maya 动画。')
                if elapsed >= timeout: raise TimeoutError('后台 Max 转换超时，请检查授权或日志。')
                time.sleep(.15)
        if not result_path.is_file():
            raise RuntimeError('后台 Max 未返回动画数据（退出码 {}），请检查 Max 安装和授权。'.format(process.returncode))
        result = json.loads(result_path.read_text(encoding='utf-8'))
        if not result.get('ok'): raise RuntimeError('后台 Max 转换失败：' + str(result.get('error', '未知错误')))
        if process.returncode != 0: raise RuntimeError('后台 Max 异常退出：' + str(process.returncode))
        data = result['data']
        if data.get('format') != 'max_biped_motion_v1' or not data.get('samples'):
            raise RuntimeError('后台 Max 返回的动画数据不完整。')
        success = True
        return data
    except Exception as exc:
        raise RuntimeError('{}\n转换日志：{}'.format(exc, directory)) from exc
    finally:
        if process is not None: _stop(process)
        if success: shutil.rmtree(directory)
