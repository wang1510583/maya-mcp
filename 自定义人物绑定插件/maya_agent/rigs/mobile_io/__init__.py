"""Portable Maya/Android exchange UI; importing this module does not change a scene."""
VERSION='1.5.1'

def show_ui():
    from .ui import show
    return show()
