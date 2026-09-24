"""Independent display layers and controller colors for each rig instance."""
from .nodes import create_records


def build(ctx):
    create_records(ctx, ctx.records("display"))
