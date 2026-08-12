"""bake.py - bake the exported Noisemaker program into a Blender Image datablock.

Run it from Blender's Text Editor (Text > Open, pick this file, then Run Script), or from a
shell with:

    blender --python bake.py

READ THIS BEFORE ADDING --background
------------------------------------
Do NOT add -b / --background. On macOS Blender cannot use the GPU without a window, and the
bake dies with:

    SystemError: GPU functions for drawing are not available in background mode

That is a Blender platform limit, not a bug in the add-on and not something a flag fixes. A
window has to be open while the bake runs; it may flash briefly and that is expected.

The add-on must already be installed and enabled: Edit > Preferences > Add-ons > Install from
Disk, pick engine/noisemaker_blender.zip, then tick "Noisemaker for Blender".
"""
import os

import bpy

# Render resolution. Output is square: SIZE by SIZE. There is no rectangular mode.
# Edit this to taste; the export does not choose a bake size for you.
SIZE = 1024

# Frames of simulation to run before capturing, and the simulated seconds each one covers.
#
# Still effects want the defaults below. Fluid, agent, reaction-diffusion and cellular-automata
# effects start from an empty state, so one frame of those is legitimately blank: for those set
# FRAMES = 1800 and TIMESTEP = 0.00167, which is about 30 seconds of evolution. That bake takes
# real time and holds the window while it runs.
FRAMES = 1
TIMESTEP = 0.0

# Where the result lands. Point a stock compositor Image node at this datablock, or drop it into
# any material or texture slot.
IMAGE_NAME = "NoisedeckExport"

# The program that shipped in this export, read from beside this script. Set an absolute path
# here instead if you move one of the two files.
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
DSL_PATH = os.path.join(HERE, "program.dsl")


def main():
    # bpy.ops.<anything> resolves to a submodule whether or not it exists, so asking bpy.ops
    # is not a test of anything. The registered operator CLASS is what actually appears, and
    # only once register_class has run.
    if not hasattr(bpy.types, "NOISEMAKER_OT_bake"):
        raise SystemExit(
            "The Noisemaker add-on is not enabled. In Blender: Edit > Preferences > Add-ons, "
            "use Install from Disk, pick engine/noisemaker_blender.zip, then tick "
            "'Noisemaker for Blender'."
        )

    if not os.path.exists(DSL_PATH):
        raise SystemExit(
            "No program.dsl next to this script (looked in %s). Keep the two files together, or "
            "edit DSL_PATH above." % HERE
        )

    result = bpy.ops.noisemaker.bake(
        filepath=DSL_PATH,
        image_name=IMAGE_NAME,
        size=SIZE,
        frames=FRAMES,
        timestep=TIMESTEP,
    )
    if "FINISHED" not in result:
        raise SystemExit(
            "Bake did not finish (%s). Blender's status bar and the system console carry the "
            "reason." % ", ".join(sorted(result))
        )

    print("[noisemaker] baked '%s' at %dx%d from %s" % (IMAGE_NAME, SIZE, SIZE, DSL_PATH))


main()
