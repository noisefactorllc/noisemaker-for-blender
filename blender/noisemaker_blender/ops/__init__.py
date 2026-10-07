"""Operators for the Noisemaker integration surface."""
from . import bake, live


def register():
    bake.register()
    live.register()


def unregister():
    live.unregister()
    bake.unregister()
