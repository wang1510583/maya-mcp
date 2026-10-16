"""Portable Maya/Android exchange UI; importing this module does not change a scene."""
VERSION='1.0.0'

def show_ui():
    from .ui import show
    return show()
