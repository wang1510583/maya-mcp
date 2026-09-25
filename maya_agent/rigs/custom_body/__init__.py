"""自定义身体绑定 — public Python API."""
from .definition import DISPLAY_NAME, VERSION


def build(namespace="customBody", on_conflict="increment", segment_count=4, height=6.0,
          use_selection=False, targets=None, copy_animation=False,
          start_frame=None, end_frame=None, sample_step=1.0):
    from .builder import build as _build
    return _build(namespace=namespace, on_conflict=on_conflict, segment_count=segment_count, height=height,
                  use_selection=use_selection, targets=targets, copy_animation=copy_animation,
                  start_frame=start_frame, end_frame=end_frame, sample_step=sample_step)


def show_ui():
    from .ui import show
    return show()


__all__ = ["build", "show_ui", "DISPLAY_NAME", "VERSION"]
