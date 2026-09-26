"""Offline extraction of reviewed nodes only. Never import the source scene."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maya_agent.rigs.soft_limb.native import commands

def main():
    study = json.loads((ROOT/'outputs/leg-study/inspection.json').read_text(encoding='utf-8'))
    names = {n['node'].rsplit('|', 1)[-1] for n in study['dag']}
    names.update(('foot_L_ctrls', 'leg_all_ctrl_L', 'recalculate_node',
                  'straight_leg_tool', 'barn_easy_IK_system', 'expression1', 'multiplyDivide1'))
    source = Path(study['scene']).read_text(encoding='gb18030')
    result, keep, found = [], False, set()
    for command in commands(source):
        verb = command.split()[0]
        if verb == 'createNode':
            kind = command.split()[1]
            name = re.search(r'-n "([^"]+)"', command).group(1)
            keep = name in names
            if keep:
                assert kind in {'transform','joint','locator','nurbsCurve','orientConstraint',
                                'parentConstraint','pointConstraint','aimConstraint',
                                'objectSet','blindDataTemplate','expression','multiplyDivide'}, kind
                found.add(name)
                result.append(command)
        elif verb == 'select':
            keep = False
        elif verb in ('setAttr', 'addAttr') and keep:
            result.append(command)
        elif verb == 'connectAttr':
            plugs = re.findall(r'"([^"]+)"', command)
            if len(plugs) == 2 and all(p.split('.')[0] in names for p in plugs):
                result.append(command)
    assert names == found, names-found
    text = '// Reviewed leg rig native graph v1; no scene scripts or settings.\n'+'\n'.join(result)+'\n'
    spec = dict(version='1.0.0', nodes=sorted(names),
        roots=[n['node'].lstrip('|') for n in study['dag'] if not n['parent']],
        world_matrices={n['node'].rsplit('|',1)[-1]:n['world_matrix'] for n in study['dag'] if 'world_matrix' in n},
        expression=next(n['expression'] for n in study['dependency_nodes'] if n['type']=='expression'),
        expression_outputs=['soft_knee_gr.translateX','pivot_feet.translateX','soft_knee_gr.translateY','multiplyDivide1.input1X'],
        controls=dict(foot='foot_L1', heel='heel_L1', toe_end='toe_end_L1', toe='toe_L1',
                      ball='tarsus_L1', knee='Knee_L', settings='strech_ik_foot1_L1', hip='joint1'),
        template_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
    data=ROOT/'maya_agent/rigs/soft_leg/data'
    data.mkdir(parents=True, exist_ok=True)
    (data/'leg_v1.ma').write_text(text,encoding='utf-8')
    (data/'leg_v1.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    print({'nodes':len(names),'roots':spec['roots']})

if __name__=='__main__':main()

