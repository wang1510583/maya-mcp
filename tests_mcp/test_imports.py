"""The Maya-side tool registry must work without external LLM HTTP dependencies."""
from pathlib import Path
import subprocess
import sys


def test_tools_import_without_site_packages_or_http_clients():
    root = Path(__file__).resolve().parents[1]
    code = '''
import importlib.abc
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
sys.path.append(str(root / ".maya-mcp-deps"))
class BlockHTTP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"httpx", "requests", "openai", "anthropic"}:
            raise ModuleNotFoundError("HTTP provider dependency forbidden: " + fullname)
sys.meta_path.insert(0, BlockHTTP())
from maya_agent.tools.registry import ensure_tools_loaded, all_tools
ensure_tools_loaded()
assert len(all_tools()) == 117
assert "maya_agent.llm.registry" not in sys.modules
assert "httpx" not in sys.modules
print("117 tools loaded without HTTP provider dependencies")
'''
    result = subprocess.run([sys.executable, "-S", "-c", code, str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
