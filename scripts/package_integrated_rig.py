"""Validate and archive the canonical standalone rig directory in place."""
import ast
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / '自定义人物绑定插件'


def build():
    if not (DESTINATION / '安装插件.py').is_file():
        raise FileNotFoundError('Missing canonical standalone rig directory')
    records = []
    for path in sorted(DESTINATION.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.name == 'manifest.json':
            continue
        if path.suffix in ('.pyc', '.pyo'):
            continue
        content = path.read_bytes()
        if path.suffix == '.py':
            ast.parse(content, filename=str(path))
        records.append(dict(path=path.relative_to(DESTINATION).as_posix(), bytes=len(content),
                            sha256=hashlib.sha256(content).hexdigest()))
    def version(relative):
        tree = ast.parse((DESTINATION / relative).read_text(encoding='utf-8'))
        return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets))
    manifest = dict(integrated_version=version('maya_agent/rigs/integrated/__init__.py'),
                    body_version=version('maya_agent/rigs/custom_body/definition.py'), files=records)
    (DESTINATION / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = ROOT / '自定义人物绑定插件.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED) as zipped:
        for record in records:
            path = DESTINATION / record['path']
            zipped.write(path, arcname=DESTINATION.name + '/' + record['path'])
        zipped.write(DESTINATION / 'manifest.json', arcname=DESTINATION.name + '/manifest.json')
    with ZipFile(archive) as zipped:
        assert zipped.testzip() is None
    print(json.dumps(dict(folder=str(DESTINATION), archive=str(archive), files=len(records),
                          bytes=sum(record['bytes'] for record in records)), ensure_ascii=False))


if __name__ == '__main__':
    build()
