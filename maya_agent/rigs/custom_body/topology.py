"""Compile variable-length topology from packaged, user-approved node prototypes.

This is pure data generation; the existing components own all Maya mutations.
Four controls retain the original graph, names, shapes and rounded slide weights.
"""
from copy import deepcopy


def compile_definition(base, segment_count, height, version, preserve_four=True):
    data = deepcopy(base)
    data.update(version=version, segment_count=segment_count, height=float(height))
    if segment_count == 4 and preserve_four:
        # Preserve the complete v1 graph, including 0.333 / 0.667 weights.
        factor = height / 6.0
        for row in data["nodes"]:
            for attr, meta in row["attributes"].items():
                if attr in {"translateX", "translateY", "translateZ", "restTranslateX",
                            "restTranslateY", "restTranslateZ", "inputTranslateY"}:
                    meta["value"] *= factor
        return data

    prefix = base["source_namespace"] + ":"
    prototypes = {n["name"].split(":")[-1]: n for n in base["nodes"]}
    data["nodes"], data["connections"] = [], []
    step = height / (segment_count - 1)
    mids = ["spine{:02d}".format(i) for i in range(1, segment_count - 1)]
    stems = ["hips"] + mids + ["chest"]
    data["controls"] = {s: s + "_ctrl" for s in stems}
    data["joints"] = ["joint{}".format(i + 1) for i in range(segment_count)]

    def clone(source, name=None, parent=None, values=None, rename_attr=None):
        row = deepcopy(prototypes[source])
        row["name"] = prefix + (name or source)
        row["parent"] = prefix + parent if parent else None
        if rename_attr:
            old, new = rename_attr
            for key in ("attributes", "custom_attributes"):
                if old in row.get(key, {}):
                    row[key][new] = row[key].pop(old)
        for key, value in (values or {}).items():
            row["attributes"][key]["value"] = value
            if key in row.get("custom_attributes", {}):
                row["custom_attributes"][key]["value"] = value
        data["nodes"].append(row)
        return row

    def edge(source, destination):
        data["connections"].append({"source": ("" if source.startswith("layerManager.") else prefix) + source,
                                    "destination": prefix + destination})

    clone("hips_zero")
    clone("hips_ctrl", parent="hips_zero")
    clone("hips_ctrlShape", parent="hips_ctrl")
    clone("chest_zero", values={"translateY": height})
    clone("group1", parent="chest_zero")
    clone("chest_ctrl", parent="group1")
    clone("chest_ctrlShape", parent="chest_ctrl")
    for i, stem in enumerate(mids, 1):
        clone("spineLower_zero", stem + "_zero", values={"translateY": step * i})
        clone("spineLower_driven", stem + "_driven", stem + "_zero")
        clone("spineLower_connect", stem + "_connect", stem + "_driven")
        clone("spineLower_ctrl", stem + "_ctrl", stem + "_connect",
              {"hipsWeight": segment_count - 1 - i, "chestWeight": i})
        clone("spineLower_ctrlShape", stem + "_ctrlShape", stem + "_ctrl")
        orient, rotation, slide = stem + "_orientConstraint", stem + "_rotation", stem + "_slide"
        clone("spineLower_orientConstraint", orient, stem + "_connect",
              {"translateY": -step * i, "target[0].targetWeight": segment_count - 1 - i,
               "target[1].targetWeight": i})
        clone("composeMatrix4", rotation)
        clone("multiplyDivide2", slide, values={"input2" + a: i / (segment_count - 1) for a in "XYZ"})
        for index, endpoint in enumerate(("hips", "chest")):
            edge(endpoint + "_ctrl.rotate", orient + ".target[{}].targetRotate".format(index))
            edge(stem + "_ctrl." + endpoint + "Weight", orient + ".target[{}].targetWeight".format(index))
        edge(orient + ".constraintRotate", stem + "_connect.rotate")
        edge(orient + ".constraintRotate", rotation + ".inputRotate")
        edge("chest_ctrl.translate", slide + ".input1")
        edge(slide + ".output", stem + "_driven.translate")

    for i in range(1, segment_count):
        offset, matrix, decompose = "offset{}".format(i), "position{}".format(i), "decompose{}".format(i)
        clone("composeMatrix1", offset, values={"inputTranslateY": step})
        clone("multMatrix1", matrix)
        clone("decomposeMatrix1", decompose)
        edge(offset + ".outputMatrix", matrix + ".matrixIn[0]")
        edge(stems[i - 1] + "_ctrl.matrix", matrix + ".matrixIn[1]")
        if i > 1:
            edge(stems[i - 1] + "_rotation.outputMatrix", matrix + ".matrixIn[2]")
            edge("translation{}.outputMatrix".format(i - 1), matrix + ".matrixIn[3]")
        edge(matrix + ".matrixSum", decompose + ".inputMatrix")
        edge(decompose + ".outputTranslate", stems[i] + "_zero.translate")
        if i < segment_count - 1:
            pick = "translation{}".format(i)
            clone("pickMatrix1", pick)
            edge(matrix + ".matrixSum", pick + ".inputMatrix")

    for i, stem in enumerate(stems):
        joint = data["joints"][i]
        constraint = joint + "_parentConstraint1"
        clone("joint1" if i == 0 else "joint2", joint,
              data["joints"][i - 1] if i else None, {"translateX": step if i else 0})
        clone("joint1_parentConstraint1" if i == 0 else "joint2_parentConstraint1",
              constraint, joint, {"restTranslateX": step if i else 0},
              ("hips_ctrlW0" if i == 0 else "spineLower_ctrlW0", stem + "_ctrlW0"))
        for source, target in (("parentMatrix", "targetParentMatrix"), ("rotate", "targetRotate"),
                               ("rotateOrder", "targetRotateOrder"), ("rotatePivot", "targetRotatePivot"),
                               ("rotatePivotTranslate", "targetRotateTranslate"), ("scale", "targetScale"),
                               ("translate", "targetTranslate")):
            edge(stem + "_ctrl." + source, constraint + ".target[0]." + target)
        for source, target in (("jointOrient", "constraintJointOrient"), ("parentInverseMatrix", "constraintParentInverseMatrix"),
                               ("rotateOrder", "constraintRotateOrder"), ("rotatePivot", "constraintRotatePivot"),
                               ("rotatePivotTranslate", "constraintRotateTranslate")):
            edge(joint + "." + source, constraint + "." + target)
        for channel in ("Rotate", "Translate"):
            for axis in "XYZ":
                edge(constraint + ".constraint" + channel + axis, joint + "." + channel.lower() + axis)
        edge(constraint + "." + stem + "_ctrlW0", constraint + ".target[0].targetWeight")
        if i:
            edge(data["joints"][i - 1] + ".scale", joint + ".inverseScale")

    for i in range(1, 4):
        clone("layer{}".format(i))
        edge("layerManager.displayLayerId[{}]".format(i), "layer{}.identification".format(i))
    for stem in stems:
        edge("layer{}.drawInfo".format(1 if stem in ("hips", "chest") else 2), stem + "_ctrl.drawOverride")
    edge("layer3.drawInfo", "joint1.drawOverride")
    return data
