"""Deformation joint hierarchy. Future joint-count changes belong here and in the template."""
from .nodes import create_records


def build(ctx):
    create_records(ctx, ctx.records("skeleton"))
