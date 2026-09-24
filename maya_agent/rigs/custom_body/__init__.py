"""自定义身体绑定 — public Python API."""
from .definition import DISPLAY_NAME, VERSION


def build(namespace="customBody", on_conflict="increment", segment_count=4, height=6.0,
          use_selection=False, targets=None):
    from .builder import build as _build
    return _build(namespace=namespace, on_conflict=on_conflict, segment_count=segment_count, height=height,
                  use_selection=use_selection, targets=targets)


def show_ui():
    from .ui import show
    return show()


__all__ = ["build", "show_ui", "DISPLAY_NAME", "VERSION"]
