"""Executed by 3dsmaxbatch.exe; input/output are JSON, never executable user text."""
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    directory = Path(os.environ['MAYA_BIP_BATCH_JOB'])
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from pymxs import runtime as rt
        from max_mcp.biped_retarget import capture
        request = json.loads((directory / 'request.json').read_text(encoding='utf-8'))
        rt.frameRate = request['fps']
        result = dict(ok=True, data=capture(request['params']))
    except Exception as exc:
        result = dict(ok=False, error=str(exc), traceback=traceback.format_exc())
    temporary = directory / 'result.tmp'
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(directory / 'result.json')


if __name__ == '__main__': main()
