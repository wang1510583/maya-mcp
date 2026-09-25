import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maya_mcp.connection import request

results=[]
for args in [(2,False),(4,True),(8,False),(8,True,False,True),(4,True,True),
             (2,False,False,False,True),(4,True,False,False,True),(4,True,True,False,True)]:
    code='import runpy\nresult=runpy.run_path('+repr(str(ROOT/'scripts/test_custom_body_animation_live.py'))+')["run_case"](*'+repr(args)+')'
    result=request('python',{'code':code})['result']
    results.append(result)
    print(json.dumps(result),flush=True)
(ROOT/'outputs/custom-body-tests/animation-tests.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
