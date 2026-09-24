"""Package just the standalone body rig, UI, shelf installers and license."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maya_agent.rigs.custom_body.definition import VERSION

files = [ROOT / name for name in ('install_custom_body_rig.py', 'install_custom_body_rig.mel',
                                  'CUSTOM_BODY_PLUGIN_README.md', 'LICENSE',
                                  'maya_agent/__init__.py', 'maya_agent/rigs/__init__.py')]
files.extend(p for p in (ROOT/'maya_agent/rigs/custom_body').rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.md'))
output = ROOT/'outputs/custom-body-plugin'
output.mkdir(parents=True, exist_ok=True)
archive = output/('custom-body-rig-v'+VERSION+'.zip')
with ZipFile(archive, 'w', ZIP_DEFLATED) as zipped:
    for path in files:
        zipped.write(path, path.relative_to(ROOT).as_posix())
with ZipFile(archive) as zipped:
    assert zipped.testzip() is None
    assert json.loads(zipped.read('maya_agent/rigs/custom_body/data/body_v3.json'))['version'] == VERSION
print(json.dumps({'archive':str(archive),'files':len(files),'bytes':archive.stat().st_size},ensure_ascii=True))
