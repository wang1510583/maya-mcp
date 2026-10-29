"""Bind the successful isolated-Maya report to the exact distributable bytes."""
import ast,base64,hashlib,io,json,sys
from pathlib import Path
from zipfile import ZipFile

def run():
    root=Path(__file__).resolve().parents[1]
    out=Path(sys.argv[sys.argv.index('--output')+1]).resolve() if '--output' in sys.argv else root/'outputs'/'runtime-assistant-test'
    report=json.loads((out/'result.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['single_file']
    for name in ('references','key_regression','elbow','foot_reach','foot_input','foot_compat'):assert report[name]['passed']
    single=root/'本草角色绑定.py'
    tree=ast.parse(single.read_bytes())
    constants={target.id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
               for target in node.targets if isinstance(target,ast.Name) and target.id in ('_SHA256','_PAYLOAD')}
    archive=(root/'本草角色绑定.zip').read_bytes()
    digest=hashlib.sha256(archive).hexdigest()
    assert digest==constants['_SHA256']
    assert base64.b64decode(constants['_PAYLOAD'])==archive
    installed=Path(report['installed_package'])
    assert installed.name==digest
    with ZipFile(io.BytesIO(archive)) as z:
        manifest=json.loads(z.read('本草角色绑定/manifest.json'))
        for row in manifest['files']:
            content=z.read('本草角色绑定/'+row['path'])
            assert hashlib.sha256(content).hexdigest()==row['sha256'],row['path']
            assert (installed/row['path']).read_bytes()==content,row['path']
            assert (root/'本草角色绑定'/row['path']).read_bytes()==content,row['path']
    full=root/'自定义人物绑定插件'
    full_manifest=json.loads((full/'manifest.json').read_text(encoding='utf-8'))
    assert full_manifest['integrated_version']==manifest['source_version']
    with ZipFile(root/'自定义人物绑定插件.zip') as z:
        for row in full_manifest['files']:
            content=(full/row['path']).read_bytes()
            assert hashlib.sha256(content).hexdigest()==row['sha256'],row['path']
            assert z.read('自定义人物绑定插件/'+row['path'])==content,row['path']
    validated=dict(version=manifest['assistant_version'],core=manifest['source_version'],
                   single_file_sha256=hashlib.sha256(single.read_bytes()).hexdigest(),archive_sha256=digest,test=report)
    (out/'validated-release.json').write_text(json.dumps(validated,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(version=validated['version'],core=validated['core'],files=len(manifest['files']),archive_sha256=digest)))

if __name__=='__main__':run()
