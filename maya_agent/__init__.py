"""Maya Agent — AI-powered assistant for Maya game development workflows."""
from pathlib import Path

_rig_package = Path(__file__).resolve().parents[1] / '自定义人物绑定插件' / 'maya_agent'
if _rig_package.is_dir() and str(_rig_package) not in __path__:
    __path__.append(str(_rig_package))

__version__ = "1.3.1"
__app_name__ = "Maya Agent"


def get_config():
    from maya_agent.utils.config import get_config as _get

    return _get()


def launch():
    from maya_agent.main import launch as _launch

    return _launch()


def bootstrap():
    from maya_agent.plugin.menu import bootstrap as _boot

    return _boot()


def reload():
    """Reload plugin code and reinstall Maya menu / shelf."""
    from maya_agent.plugin.menu import reload_plugin

    return reload_plugin()


__all__ = ["__version__", "__app_name__", "get_config", "launch", "bootstrap", "reload"]
