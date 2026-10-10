import json
from pathlib import Path
import pytest
from max_mcp import batch_client as batch
from max_mcp.biped_retarget import PAIRS


@pytest.fixture
def job(tmp_path, monkeypatch):
    path = tmp_path / '中文 空格.bip'
    path.write_bytes(b'test')
    exe = tmp_path / '3dsmaxbatch.exe'
    exe.touch()
    monkeypatch.setattr(batch, 'installations', lambda: [str(exe)])
    directory = tmp_path / 'job'
    directory.mkdir()
    monkeypatch.setattr(batch.tempfile, 'mkdtemp', lambda **_: str(directory))
    names = sorted({n for pair in PAIRS for n in pair})
    profile = dict(points={n: [i, i*.5, 100-i*2] for i, n in enumerate(names)})
    return dict(bip_path=str(path), profile=profile, step=.5), directory


def fake_process(monkeypatch, payload=None, code=0, running=False):
    calls = []
    class Process:
        returncode = code
        pid = 987654321
        def poll(self): return None if running else self.returncode
    def launch(args, **kwargs):
        calls.append((args, kwargs))
        directory = Path(kwargs['env']['MAYA_BIP_BATCH_JOB'])
        if payload is not None:
            (directory/'result.json').write_text(json.dumps(payload), encoding='utf8')
        return Process()
    monkeypatch.setattr(batch.subprocess, 'Popen', launch)
    monkeypatch.setattr(batch, '_stop', lambda process: calls.append(('stopped', process.pid)))
    return calls


def test_file_roundtrip_no_socket(job, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: pytest.fail('No socket allowed'))
    params, directory = job
    data = dict(format='max_biped_motion_v1', samples=[{'frame':0}], source_keys={'tracks':{}})
    calls = fake_process(monkeypatch, dict(ok=True, data=data))
    assert batch.capture(params) == data
    assert not directory.exists()
    args, options = calls[0]
    assert isinstance(args, list) and args[1].endswith('batch_worker.py')
    assert 'shell' not in options
    assert 'PYTHONPATH' not in options['env']


@pytest.mark.parametrize('payload,code,match', [
    (None, 1, '未返回'),
    ({'ok':False,'error':'Bad BIP'}, 0, 'Bad BIP'),
    ({'ok':True,'data':{}}, 0, '不完整'),
    ({'ok':True,'data':{}}, 3, '异常退出'),
])
def test_failures_retain_logs(job, monkeypatch, payload, code, match):
    params, directory = job
    fake_process(monkeypatch, payload, code)
    with pytest.raises(RuntimeError, match=match): batch.capture(params)
    assert (directory/'request.json').is_file()
    assert (directory/'batch.log').is_file()


def test_cancel_stops_only_owned_process(job, monkeypatch):
    params, directory = job
    calls = fake_process(monkeypatch, running=True)
    with pytest.raises(RuntimeError, match='取消'): batch.capture(params, progress=lambda _:False)
    assert calls[-1] == ('stopped', 987654321)


def test_timeout_stops_owned_process(job, monkeypatch):
    params, directory = job
    calls = fake_process(monkeypatch, running=True)
    ticks = iter([0, 2])
    monkeypatch.setattr(batch.time, 'monotonic', lambda:next(ticks))
    with pytest.raises(RuntimeError, match='超时'): batch.capture(params, timeout=1)
    assert calls[-1] == ('stopped', 987654321)


@pytest.mark.parametrize('step', [0, -1, float('nan'), float('inf')])
def test_bad_step_fails_before_launch(job, step):
    params, directory = job
    params['step'] = step
    with pytest.raises(ValueError, match='间隔'): batch.capture(params)
    assert not (directory/'request.json').exists()


def test_missing_file_no_connection():
    with pytest.raises(ValueError, match='bip'): batch.capture({'bip_path':None})


def test_api_file_defaults_to_batch(job, monkeypatch):
    from maya_agent.rigs import bip_retarget as br
    from max_mcp import connection
    params, _ = job
    sentinel = {'sentinel':True}
    monkeypatch.setattr(connection, 'request', lambda *a, **kw:pytest.fail('File import used live MCP'))
    monkeypatch.setattr(br, 'target_profile', lambda *a:params['profile'])
    def capture(p, **kw):
        assert p['bip_path'] == params['bip_path']
        assert kw['fps'] == 24
        return sentinel
    monkeypatch.setattr(batch, 'capture', capture)
    monkeypatch.setattr(br, 'retarget', lambda data, **kw: (data, kw))
    result, options = br.retarget_max_bip(bip_path=params['bip_path'], max_fps=24, key_mode='source', output_start=10)
    assert result is sentinel
    assert options == {'start_frame':10, 'key_mode':'source'}


def test_batch_requires_file_and_native():
    from maya_agent.rigs.bip_retarget import retarget_max_bip
    with pytest.raises(ValueError, match='文件'): retarget_max_bip(backend='batch')
    with pytest.raises(ValueError, match='原生'): retarget_max_bip(backend='batch',native_adaptation=False)


def test_maya_dll_paths_do_not_leak_to_max(tmp_path, monkeypatch):
    import os
    maya = tmp_path/'maya2024'
    arnold = tmp_path/'mtoadeploy'/'bin'
    external = tmp_path/'Autodesk'/'Arnold'/'maya2024'/'bin'
    safe = tmp_path/'system'
    monkeypatch.setenv('MAYA_LOCATION', str(maya))
    monkeypatch.setenv('QT_PLUGIN_PATH', str(maya/'plugins'))
    monkeypatch.setenv('ARNOLD_PLUGIN_PATH', str(arnold))
    monkeypatch.setenv('PATH', os.pathsep.join(map(str, [maya/'bin', arnold, external, safe])))
    before = os.environ.copy()
    result = batch._environment(tmp_path/'max'/'3dsmaxbatch.exe', tmp_path/'job')
    assert result['PATH'].split(os.pathsep) == [str(tmp_path/'max'), str(safe)]
    assert not {'MAYA_LOCATION','QT_PLUGIN_PATH','ARNOLD_PLUGIN_PATH'} & result.keys()
    assert os.environ == before


@pytest.mark.skipif(batch.os.name != 'nt', reason='Windows DLL directory inheritance')
@pytest.mark.parametrize('failed', [False, True])
def test_launch_restores_host_dll_directory(tmp_path, monkeypatch, failed):
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    def directory():
        buf = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(buf), buf)
        return buf.value
    original = directory()
    kernel.SetDllDirectoryW(ctypes.c_wchar_p(str(tmp_path)))
    def popen(*args, **kwargs):
        assert directory() == ''
        if failed: raise OSError('launch failed')
        return 'owned-process'
    monkeypatch.setattr(batch.subprocess, 'Popen', popen)
    try:
        if failed:
            with pytest.raises(OSError, match='launch failed'): batch._launch(['test'])
        else: assert batch._launch(['test']) == 'owned-process'
        assert directory() == str(tmp_path)
    finally:
        kernel.SetDllDirectoryW(ctypes.c_wchar_p(original) if original else None)
