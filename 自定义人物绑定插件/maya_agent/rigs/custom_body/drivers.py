"""Matrix positioning, weighted rotation and controller-to-joint constraints."""
from .nodes import create_records


def build(ctx):
    create_records(ctx, ctx.records("drivers"))


def connect(ctx):
    c = ctx.cmds
    for edge in ctx.definition["connections"]:
        source, destination = ctx.name(edge["source"]), ctx.name(edge["destination"])
        if source.startswith("layerManager.displayLayerId["):
            # Maya assigns fresh layer IDs. Reusing captured IDs would couple rig instances.
            actual = c.connectionInfo(destination, sourceFromDestination=True)
            if not actual.startswith("layerManager.displayLayerId["):
                raise RuntimeError("Display layer was not registered: " + destination)
            ctx.layer_connections.append({"source": actual, "destination": destination})
            continue
        if not c.isConnected(source, destination):
            c.connectAttr(source, destination, force=False)
