"""Build the animator distribution from the canonical rig core, never stale copies."""
import ast
import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'自定义人物绑定插件'
DEST=ROOT/'本草角色绑定'


def build():
    payload={}
    for path in (SOURCE/'maya_agent').rglob('*'):
        rel=path.relative_to(SOURCE)
        if not path.is_file() or '__pycache__' in rel.parts:continue
        if path.suffix not in ('.py','.json'):continue
        if 'mobile_io' in rel.parts or path.name.startswith('bip_'):continue
        if path.name=='ui.py' or path.name.endswith('_ui.py') or path.name=='ui_common.py':continue
        payload[rel.as_posix()]=path.read_bytes()
    for path in (ROOT/'runtime_assistant').iterdir():
        if path.suffix in ('.py','.md'):payload[path.name]=path.read_bytes()
    for name,content in payload.items():
        if name.endswith('.py'):ast.parse(content,filename=name)
    tree=ast.parse(payload['maya_agent/rigs/integrated/__init__.py'])
    version=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets))
    records=[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in sorted(payload.items())]
    manifest=dict(assistant_version='1.0.6',source_version=version,files=records)
    payload['manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    DEST.mkdir(exist_ok=True)
    # Remove only previously generated manifest entries, never unrelated files.
    if (DEST/'manifest.json').exists():
        old=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'))
        for row in old['files']:
            target=(DEST/row['path']).resolve()
            if not target.is_relative_to(DEST.resolve()):raise ValueError('Invalid old manifest path')
            if row['path'] not in payload and target.is_file():target.unlink()
    for name,content in payload.items():
        path=DEST/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    archive=ROOT/'本草角色绑定.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as z:
        for name,content in sorted(payload.items()):z.writestr(DEST.name+'/'+name,content)
    with ZipFile(archive) as z:assert z.testzip() is None
    content=archive.read_bytes()
    template=(ROOT/'scripts'/'runtime_single_file_template.py').read_text(encoding='utf-8')
    single=template.replace('__ARCHIVE_SHA256__',hashlib.sha256(content).hexdigest()).replace('__ARCHIVE_BASE64__',base64.encodebytes(content).decode('ascii'))
    ast.parse(single)
    standalone=ROOT/'本草角色绑定.py'
    standalone.write_text(single,encoding='utf-8')
    print(json.dumps(dict(files=len(records),bytes=archive.stat().st_size,core=version,archive=str(archive),single_file=str(standalone),single_file_bytes=standalone.stat().st_size),ensure_ascii=False))


if __name__=='__main__':build()
