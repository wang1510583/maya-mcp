"""Native Maya node/curve creation and exact captured attribute restoration."""


def create_records(ctx, records):
    import maya.api.OpenMaya as om
    c = ctx.cmds
    pending = list(records)
    while pending:
        ready = [n for n in pending if not n["parent"] or c.objExists(ctx.name(n["parent"]))]
        if not ready:
            raise RuntimeError("Unresolved parent hierarchy in custom body rig")
        for row in ready:
            name, parent = ctx.name(row["name"]), ctx.name(row["parent"])
            if c.objExists(name):
                raise RuntimeError("Refusing to overwrite node: " + name)
            if row["type"] == "nurbsCurve":
                curve = row["curve"]
                selection = om.MSelectionList()
                selection.add(parent)
                obj = om.MFnNurbsCurve().create(
                    om.MPointArray([om.MPoint(*p) for p in curve["cvs"]]),
                    om.MDoubleArray(curve["knots"]), curve["degree"], curve["form"],
                    False, False, selection.getDependNode(0))
                path = om.MFnDagNode(obj).fullPathName()
                ctx.created.append(path)
                c.rename(path, name)
                ctx.created[-1] = name
            elif row["type"] == "displayLayer":
                # Keep namespace assignment in an explicit rename; Maya 2024's
                # createDisplayLayer(name='ns:layer') can lose the prefix on redo.
                temporary = c.createDisplayLayer(empty=True)
                ctx.created.append(temporary)
                c.rename(temporary, name)
                ctx.created[-1] = name
            else:
                kwargs = {"name": name, "skipSelect": True}
                if parent:
                    kwargs["parent"] = parent
                c.createNode(row["type"], **kwargs)
                ctx.created.append(name)
            for attr, meta in row.get("custom_attributes", {}).items():
                c.addAttr(name, longName=attr, attributeType=meta["type"], defaultValue=meta["value"],
                          keyable=row["attributes"][attr]["keyable"])
            pending.remove(row)


def restore_values(ctx):
    c = ctx.cmds
    for row in ctx.definition["nodes"]:
        for attr, meta in row["attributes"].items():
            if row["type"] == "displayLayer" and attr == "identification":
                continue
            plug = ctx.name(row["name"]) + "." + attr
            c.setAttr(plug, lock=False)
            if c.connectionInfo(plug, isDestination=True):
                continue
            if meta["type"] == "matrix":
                c.setAttr(plug, *meta["value"], type="matrix")
            else:
                c.setAttr(plug, meta["value"])


def restore_channel_flags(ctx):
    for row in ctx.definition["nodes"]:
        for attr, meta in row["attributes"].items():
            ctx.cmds.setAttr(ctx.name(row["name"]) + "." + attr,
                             keyable=meta["keyable"], lock=meta["locked"])
