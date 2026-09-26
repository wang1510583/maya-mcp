"""Build a source-only GitHub upload snapshot without credentials or Maya scenes."""
from pathlib import Path
import fnmatch
import hashlib
import json
import re
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "github-publish"
DIRECTORIES = ("maya_agent", "maya_mcp", "scripts", "tests_mcp", "resources", "config", "docs")
ROOT_FILES = (".gitignore", "AGENTS.md", "LICENSE", "README.md", "MAYA_MCP_README.md",
              "CUSTOM_BODY_PLUGIN_README.md", "install_custom_body_rig.py", "install_custom_body_rig.mel",
              "install_custom_arm_rig.py", "install_custom_leg_rig.py", "install_integrated_rig.py",
              "pyproject.toml", "requirements.txt", "requirements-mcp.txt", "install.bat",
              "install_dragdrop.mel", "install_maya_mcp.mel", "install_maya_mcp.ps1",
              "run_maya_mcp.bat", "uninstall.bat")
SECRET_PATTERNS = [re.compile(pattern) for pattern in (
    r"gh[pousr]_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{30,}",
    r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)]


def main():
    ignore = [line.strip() for line in (ROOT / '.gitignore').read_text(encoding='utf-8-sig').splitlines()
              if line.strip() and not line.startswith('#')]

    def ignored(path):
        relative = path.relative_to(ROOT).as_posix()
        excluded = False
        for rule in ignore:
            negated = rule.startswith('!')
            pattern = rule[1:] if negated else rule
            if ((pattern.endswith('/') and pattern.rstrip('/') in path.relative_to(ROOT).parts)
                    or fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern)):
                excluded = not negated
        return excluded

    paths = [ROOT / name for name in ROOT_FILES]
    for name in DIRECTORIES:
        paths.extend(path for path in (ROOT / name).rglob('*') if path.is_file() and not ignored(path))
    records = []
    snapshots = []
    for path in sorted(set(paths)):
        content = path.read_bytes()
        text = content.decode('utf-8-sig')
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise ValueError('Potential credential detected in ' + str(path.relative_to(ROOT)))
        relative = path.relative_to(ROOT).as_posix()
        records.append({'path': relative, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        snapshots.append((relative, content))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Fresh snapshot directory makes repeated exports independent of stale files.
    from datetime import datetime
    import uuid
    folder = OUTPUT / ('source-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    folder.mkdir()
    for relative, content in snapshots:
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    archive = OUTPUT / (folder.name + '.zip')
    with ZipFile(archive, 'w', ZIP_DEFLATED) as zipped:
        for relative, content in snapshots:
            zipped.writestr(relative, content)
    with ZipFile(archive) as zipped:
        assert zipped.testzip() is None
    manifest = {'source': str(folder), 'archive': str(archive), 'file_count': len(records),
                'total_bytes': sum(row['bytes'] for row in records), 'files': records}
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'files'}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
