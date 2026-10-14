"""Display component compatibility hook; v1.3.2 uses direct DAG overrides."""
from .nodes import create_records


def build(ctx):
    create_records(ctx, ctx.records("display"))
