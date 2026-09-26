"""Extract only the reviewed rig graph from a Maya-selected export and its metadata."""
import hashlib
import json
from pathlib import Path
import re
import sys


def package(source, output):
    text=(source/'source.ma').read_text(encoding='utf-8')
    meta=json.loads((source/'source.json').read_text(encoding='utf-8'))
    body=text[text.index('createNode '):text.index('select -ne ')]
    body=re.sub(r'^\s*rename -uid [^\n]+\n','',body,flags=re.M)
    edges=[]
    # Maya wraps connectAttr -l and other flags across lines. Preserve whole commands.
    for command in re.findall(r'^connectAttr\b[\s\S]*?;',text,re.M):
        plugs=re.findall(r'"([^"]+)"',command)
        assert len(plugs)==2
        names=[p.split('.')[0] for p in plugs]
        if all(n in meta['nodes'] for n in names):
            edges.append(re.sub(r'\s+', ' ', command))
        else:
            assert names==['multiplyDivide3',':defaultRenderUtilityList1'],names
    asset=('//Maya ASCII 2024 scene\n// Clean captured rig graph; no default scene edits or scriptNodes.\n'
           'requires maya "2024";\nrequires -nodeType "quatToEuler" "quatNodes" "1.0";\n'
           +body+'\n'.join(edges)+'\n')
    assert len(re.findall(r'^createNode ',asset,re.M))==len(meta['nodes'])
    assert not re.search(r'^createNode (script|unknown)\b|^select |^currentUnit |^file |rename -uid',asset,re.M)
    output.mkdir(parents=True,exist_ok=True)
    (output/'limb_v1.ma').write_text(asset,encoding='utf-8')
    spec={k:meta[k] for k in ('roots','nodes','node_types','world_matrices','linear_unit','expression')}
    spec.update(version='1.0.0',schema_version=1,template_sha256=hashlib.sha256(asset.encode()).hexdigest(),
                internal_connections=len(edges),controls={'shoulder_fk':'shldrFK_L1','middle_fk':'armFK_L1',
                'end_fk':'handFK_L1','end_locator':'hand_L1','pole_locator':'elb_L1',
                'parameters':'strech_ik_foot1','roll':'elbow_roll1'})
    (output/'limb_v1.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'nodes':len(spec['nodes']),'connections':len(edges),'template_bytes':len(asset.encode())}


if __name__=='__main__':
    print(json.dumps(package(Path(sys.argv[1]),Path(sys.argv[2]))))
