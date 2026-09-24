"""Install/start from Maya, or install startup hooks from external Python."""
import argparse
import json
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# >>> Maya MCP"
END = "# <<< Maya MCP"


def startup_block():
    return '''# >>> Maya MCP
def _maya_mcp_startup():
    import sys
    root = {root!r}
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from maya_mcp.install import activate
        activate()
    except Exception as exc:
        print("[Maya MCP] Startup failed:", exc)
import maya.cmds as _maya_mcp_cmds
if not _maya_mcp_cmds.about(batch=True):
    import maya.utils as _maya_mcp_utils
    _maya_mcp_utils.executeDeferred(_maya_mcp_startup)
# <<< Maya MCP
'''.format(root=str(ROOT))


def install_startup(scripts_dir, remove=False):
    scripts_dir = Path(scripts_dir)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / "userSetup.py"
    raw = path.read_bytes() if path.exists() else b""
    # Preserve preexisting code and its encoding/BOM. Only our ASCII markers are replaced.
    pattern = re.compile(rb"(?m)^# >>> Maya MCP\r?\n.*?^# <<< Maya MCP\r?\n?", re.S)
    clean = pattern.sub(b"", raw)
    if remove:
        updated = clean
    else:
        block = startup_block().encode("utf-8")
        updated = clean + (b"\n" if clean and not clean.endswith(b"\n") else b"") + block
    if updated != raw:
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            shutil.copy2(path, path.with_name("userSetup.py.maya-mcp-" + stamp + ".bak"))
        path.write_bytes(updated)
    return path


def vendor_yaml():
    import yaml
    source = Path(yaml.__file__).parent
    target = ROOT / ".maya-mcp-deps" / "yaml"
    target.mkdir(parents=True, exist_ok=True)
    for item in source.glob("*.py"):
        shutil.copy2(item, target / item.name)
    # The Python fallback works across Maya's bundled Python versions.
    import importlib.metadata
    dist = importlib.metadata.distribution("PyYAML")
    for item in dist.files or []:
        if str(item).endswith("LICENSE"):
            shutil.copy2(dist.locate_file(item), target.parent / "PyYAML-LICENSE")


def activate():
    import maya.cmds as cmds
    import maya.mel as mel
    from .bridge import start, stop
    start()
    shelf = "MayaMCP"
    if not cmds.shelfLayout(shelf, exists=True):
        top = mel.eval("$tmp=$gShelfTopLevel")
        cmds.shelfLayout(shelf, parent=top)
    existing = {cmds.shelfButton(c, query=True, label=True)
                for c in (cmds.shelfLayout(shelf, query=True, childArray=True) or [])
                if cmds.objectTypeUI(c) == "shelfButton"}
    for label, command, tip in [
        ("Start", "from maya_mcp.bridge import start; start()", "Start local Maya MCP bridge"),
        ("Stop", "from maya_mcp.bridge import stop; stop()", "Stop local Maya MCP bridge"),
    ]:
        if label not in existing:
            cmds.shelfButton(parent=shelf, label=label, image="commandButton.png",
                             imageOverlayLabel=label, annotation=tip,
                             sourceType="python", command=command)


def install_in_maya():
    import maya.cmds as cmds
    install_startup(cmds.internalVar(userScriptDir=True))
    activate()
    print("[Maya MCP] Installed. Start/Stop buttons are on the MayaMCP shelf.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scripts-dir")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        vendor_yaml()
        from .connection import ensure_settings, settings_path, INSTALLATION_PATH
        ensure_settings()
        INSTALLATION_PATH.write_text(json.dumps({"config_path": str(settings_path().resolve())}, indent=2), encoding="utf-8")
        print("Prepared Maya dependencies and local connection settings")
    if args.scripts_dir:
        print(install_startup(args.scripts_dir, remove=args.remove))
