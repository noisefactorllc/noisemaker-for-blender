"""Noisemaker for Blender add-on package.

This package has two faces:

1. A plain Python library (``.compiler`` / ``.runtime`` / ``.backend``) imported by the
   parity gates and the render harness. ``.compiler`` is stdlib-only and is imported
   OUTSIDE Blender (plain ``python3``) by the byte-exact gates — so this module body
   MUST NOT ``import bpy`` at top level.

2. A registerable Blender addon. ``register()`` lazily imports the bpy-dependent
   submodules (``.props`` / ``.ops`` / ``.nodes`` / ``.ui``) so enabling the addon
   wires up the integration surface (the bake-to-Image operator, the CUSTOM node
   tree, and the N-panels) without that import ever running under the gates.

The integration surface is "compositor-feeding" (docs/BLENDER-PLATFORM-NOTES.md §1):
the compositor's node set is C-defined and closed to Python, so we render via the gpu
module, bake into an Image datablock, and let the stock compositor Image node consume it.
"""

bl_info = {
    "name": "Noisemaker for Blender",
    "author": "Noise Factory LLC",
    "version": (0, 1, 0),
    "blender": (5, 1, 0),
    "location": "Compositor / Image Editor > Sidebar > Noisemaker; Noisemaker node editor",
    "description": "Noisemaker for Blender: Polymorphic-DSL procedural texture engine that bakes to an Image",
    "category": "Compositing",
}

# Submodules registered in dependency order: the PropertyGroup + Scene pointer first,
# then the operator that consumes settings, then the node tree and panels that drive it.
_MODULES = ("props", "ops", "nodes", "ui")


def register():
    import importlib
    for name in _MODULES:
        importlib.import_module("." + name, __name__).register()


def unregister():
    import importlib
    for name in reversed(_MODULES):
        importlib.import_module("." + name, __name__).unregister()
