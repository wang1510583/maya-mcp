import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from maya_mcp.connection import request

code = 'import runpy\nresult = runpy.run_path(' + repr(str(root/'scripts/test_custom_body_live.py')) + ')["result"]'
print(json.dumps(request('python',{'code':code}),ensure_ascii=True,indent=2))
