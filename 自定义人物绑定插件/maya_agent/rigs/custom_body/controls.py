"""Four curve controls, zero/driven/connect groups and user-facing weight attributes."""
from .nodes import create_records


def build(ctx):
    create_records(ctx, ctx.records("controls"))
