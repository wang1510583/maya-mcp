import importlib.util
from pathlib import Path
import pytest

path=Path(__file__).resolve().parents[1]/'自定义人物绑定插件/maya_agent/rigs/fingers/__init__.py'
spec=importlib.util.spec_from_file_location('finger_topology',path)
fingers=importlib.util.module_from_spec(spec);spec.loader.exec_module(fingers)


@pytest.mark.parametrize('lengths',[[3]*5,[1,2,4,3,2,1],[1],[8,2]])
def test_layer_order_and_unequal_fingers(lengths):
    chains=[[f'{i}_{j}' for j in range(length)] for i,length in enumerate(lengths)]
    parents={n:chain[j-1] if j else 'wrist' for chain in chains for j,n in enumerate(chain)}
    names=[chain[j] for j in range(max(lengths)) for chain in chains if j<len(chain)]
    assert fingers.chains_from_parents(names,parents)==(chains,'wrist')


@pytest.mark.parametrize('names,parents',[
    ([],{}),(['a','a'],{'a':'wrist'}),
    (['a','b'],{'a':'left','b':'right'}),
    (['a','b','c'],{'a':'wrist','b':'a','c':'a'}),
    (['a','c'],{'a':'wrist','c':'b'}),
    (['a','b'],{'a':'b','b':'a'})])
def test_reject_ambiguous_or_broken_selection(names,parents):
    with pytest.raises(ValueError):fingers.chains_from_parents(names,parents)
