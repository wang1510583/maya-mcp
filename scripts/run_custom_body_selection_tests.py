import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request

results=[]
for args in [(2,False,False,False),(4,True,True,False),(8,False,True,False),(3,True,True,True)]:
    code='import runpy\ntest=runpy.run_path('+repr(str(ROOT/'scripts/test_custom_body_selection_live.py'))+')\n'
    code+='result=test["run_case"](*'+repr(args)+')'
    result=request('python',{'code':code})['result']
    results.append(result)
    print(json.dumps(result,ensure_ascii=True),flush=True)
path=ROOT/'outputs/custom-body-tests/selection-tests.json'
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
