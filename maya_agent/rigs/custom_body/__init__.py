"""自定义身体绑定 — public Python API."""
from .definition import DISPLAY_NAME, VERSION


def build(namespace="customBody", on_conflict="increment", segment_count=4, height=6.0):
    from .builder import build as _build
    return _build(namespace=namespace, on_conflict=on_conflict, segment_count=segment_count, height=height)


__all__ = ["build", "DISPLAY_NAME", "VERSION"]
