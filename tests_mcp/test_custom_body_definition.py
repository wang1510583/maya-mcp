import json
import math
import pytest

from maya_agent.rigs.custom_body.definition import DATA_PATH, VERSION, load_definition


def test_four_segment_graph_is_backwards_compatible():
    original = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    current = load_definition()
    for field in ("nodes", "connections", "controls", "joints", "linear_unit"):
        assert current[field] == original[field]
    assert current["version"] == VERSION


@pytest.mark.parametrize("count", [2, 3, 6, 8, 64])
def test_variable_graph_is_closed_and_uniquely_connected(count):
    data = load_definition(count, 12)
    names = {n["name"] for n in data["nodes"]}
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
