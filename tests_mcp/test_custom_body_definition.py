import json
import math
import pytest

from maya_agent.rigs.custom_body.definition import DATA_PATH, VERSION, load_definition


def test_four_segment_solver_is_preserved_without_classification_layers():
    original = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    current = load_definition()
    for field in ("controls", "joints", "linear_unit"):
        assert current[field] == original[field]
    old_nodes = {n['name']: n for n in original['nodes'] if n['type'] != 'displayLayer'}
    assert {n['name'] for n in current['nodes']} == set(old_nodes)
    for node in current['nodes']:
        old = old_nodes[node['name']]
        assert {k: v for k, v in node.items() if k != 'attributes'} == {
            k: v for k, v in old.items() if k != 'attributes'}
        for attr, value in old['attributes'].items():
            if not attr.startswith('override') and attr != 'hideOnPlayback':
                assert node['attributes'][attr] == value
    assert current['connections'] == [e for e in original['connections']
                                     if e['source'].split('.')[0] in old_nodes
                                     and e['destination'].split('.')[0] in old_nodes]
    assert len(current['nodes']) == 42 and len(current['connections']) == 113
    assert current["version"] == VERSION


@pytest.mark.parametrize("count", [2, 3, 6, 8, 64])
def test_variable_graph_is_closed_and_uniquely_connected(count):
    data = load_definition(count, 12)
    names = {n["name"] for n in data["nodes"]}
    assert not any(n['type'] == 'displayLayer' for n in data['nodes'])
    assert len(names) == len(data["nodes"])
    assert len(data["controls"]) == len(data["joints"]) == count
    assert len([n for n in data["nodes"] if n["type"] == "parentConstraint"]) == count
    assert len([n for n in data["nodes"] if n["type"] == "orientConstraint"]) == count - 2
    targets = []
    for edge in data["connections"]:
        assert edge["source"].split(".")[0] in names | {"layerManager"}
        assert edge["destination"].split(".")[0] in names
        targets.append(edge["destination"])
    assert len(set(targets)) == len(targets)
    for node in data["nodes"]:
        assert not node["parent"] or node["parent"] in names


@pytest.mark.parametrize("count", [True, 1, 65, 4.0, "6", None])
def test_bad_count_is_rejected_without_maya(count):
    with pytest.raises(ValueError):
        load_definition(count)


@pytest.mark.parametrize("height", [True, 0, -1, math.inf, math.nan, "12", None])
def test_bad_height_is_rejected_without_maya(height):
    with pytest.raises(ValueError):
        load_definition(height=height)
