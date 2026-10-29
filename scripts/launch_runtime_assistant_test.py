"""Launch a hidden, separate GUI Maya with isolated preferences and no user setup."""
import os,subprocess,sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=Path(sys.argv[sys.argv.index('--output')+1]).resolve() if '--output' in sys.argv else ROOT/'outputs'/'runtime-assistant-test'
out.mkdir(parents=True,exist_ok=True)
if (out/'result.json').exists():(out/'result.json').rename(out/('result-'+str(time.time_ns())+'.json'))
env=os.environ.copy()
prefs=Path(sys.argv[sys.argv.index('--prefs')+1]).resolve() if '--prefs' in sys.argv else out/'clean_prefs'
env.update(MAYA_APP_DIR=str(prefs),MAYA_SKIP_USERSETUP_PY='1',PYTHONPATH='',MAYA_SCRIPT_PATH='',BENCAO_TEST_OUT=str(out))
env['BENCAO_TEST_SINGLE_FILE']='1' if '--single-file' in sys.argv else '0'
env['BENCAO_TEST_REFERENCES']='1' if '--references' in sys.argv else '0'
env['BENCAO_TEST_KEYS']='1' if '--keys' in sys.argv else '0'
env['BENCAO_TEST_KEEP_ALIVE']='1' if '--keep-alive' in sys.argv else '0'
env['BENCAO_TEST_KEY_REGRESSION']='1' if '--key-regression' in sys.argv else '0'
env['BENCAO_TEST_ELBOW']='1' if '--elbow' in sys.argv else '0'
env['BENCAO_TEST_FOOT_REACH']='1' if '--foot-reach' in sys.argv else '0'
env['BENCAO_TEST_FOOT_INPUT']='1' if '--foot-input' in sys.argv else '0'
test=ROOT/'scripts'/'test_runtime_assistant_isolated.py'
command='python("import runpy, maya.utils; maya.utils.executeDeferred(lambda: runpy.run_path(\'%s\'))")'%test.as_posix()
info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
with (out/'maya.log').open('w') as log:
    p=subprocess.Popen([r'D:/maya2024/Maya2024/bin/maya.exe','-noAutoloadPlugins','-command',command],env=env,stdout=log,stderr=subprocess.STDOUT,startupinfo=info,cwd=str(out))
(out/'pid.json').write_text(json.dumps(dict(pid=p.pid)),encoding='utf-8')
print(p.pid)
