"""Drag into Maya to open the BIP animation importer."""
import sys
from pathlib import Path


def install():
    root=str(Path(__file__).resolve().parent)
    if root not in sys.path:sys.path.insert(0,root)
    import importlib
    from maya_agent.rigs import bip_reference, bip_sparse, bip_retarget, bip_retarget_ui
    from max_mcp import batch_client
    for module in (batch_client, bip_reference, bip_sparse, bip_retarget, bip_retarget_ui):importlib.reload(module)
    return bip_retarget_ui.show_ui()


def onMayaDroppedPythonFile(*_):return install()
if __name__=='__main__':install()
