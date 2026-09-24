"""External runner; each Maya request tests one count and cleans its own nodes."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maya_mcp.connection import request

reports = []
for count, height in [(2, 6), (3, 6), (4, 12), (6, 10), (8, 14), (64, 126)]:
    code = 'import runpy\n'
    code += 'test = runpy.run_path(' + repr(str(ROOT/'scripts/test_custom_body_adjustable_live.py')) + ')\n'
    code += 'result = test["run_case"](' + repr(count) + ', ' + repr(height) + ')'
    response = request('python', {'code': code})
    reports.append(response['result'])
    print(json.dumps(response, ensure_ascii=True), flush=True)
(ROOT/'outputs/custom-body-tests/adjustable-tests.json').write_text(
    json.dumps(reports, indent=2, ensure_ascii=False), encoding='utf-8')
