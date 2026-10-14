"""Compatibility entry point for the standalone character rig folder."""
from pathlib import Path
import runpy


def install():
    launcher = Path(__file__).resolve().parent / "自定义人物绑定插件" / "安装插件.py"
    if not launcher.is_file():
        raise RuntimeError("未找到自定义人物绑定插件文件夹，请保留完整插件目录。")
    return runpy.run_path(str(launcher))["install"]()


def onMayaDroppedPythonFile(*args):
    return install()


if __name__ == "__main__":
    install()
