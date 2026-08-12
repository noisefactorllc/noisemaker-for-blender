# {{NM_PROGRAM_NAME}}

A Blender add-on and your program, exported from Noisedeck. Blender's compositor cannot run custom
shader code, so the add-on does not add effect nodes. It **bakes** your program into an ordinary
Blender **Image** datablock, which the compositor, any material and any texture slot can then use
like a picture. It fetches nothing at runtime.

## Install the add-on

1. Unzip this folder anywhere. Leave `engine/noisemaker_blender.zip` zipped: Blender wants the
   archive, not its contents.
2. In Blender, open **Edit > Preferences > Add-ons**, use **Install from Disk**, and pick
   `engine/noisemaker_blender.zip`.
3. Tick **Noisemaker for Blender** in the add-on list to enable it.

You need Blender 5.1 or newer and a working GPU: the add-on renders through Blender's `gpu` module.

## Bake your program

1. Open the **Compositor** or the **Image Editor** and press **N** to show the sidebar, then pick
   the **Noisemaker** tab.
2. Set **Source** to **File** and point **DSL File** at the `program.dsl` in this folder.
3. Press **Bake**.

The result lands in an Image datablock (named `Noisemaker` unless you change **Image**). Add a stock
**Image** node in the compositor pointing at it, or drop it into any material.

`bake.py` does the same thing from a script if you would rather not click: open it in Blender's Text
Editor and press **Run Script**. It reads the `program.dsl` sitting beside it and writes to an Image
called `NoisedeckExport`, with the resolution, frame count and timestep as constants at the top.

### Simulations need time to evolve

Fluid, agent, reaction-diffusion and cellular-automata effects start from an empty state, so a
single frame of one is legitimately blank. For those, raise **Frames** to about **1800** and set
**Timestep** to **0.00167**, which is roughly 30 seconds of simulated time. Programs made only of
still effects want the defaults (**Frames** 1, **Timestep** 0).

A long bake takes real time and holds the window while it runs.

## Two constraints worth knowing

**Baking is GUI-only on macOS.** Blender cannot draw on the GPU under `--background` there, so a
window has to be open while a bake runs. A scripted bake started with `blender --background` fails
with `SystemError: GPU functions for drawing are not available in background mode`. Run Blender
normally and use the Text Editor, or `blender --python bake.py` without `--background`, and let the
window flash.

**Output is square.** The bake renders at `size` by `size`. There is no rectangular mode yet.

## What's inside

| Path | What it is |
| --- | --- |
| `program.dsl` | Your program's source, exactly as Noisedeck had it. |
| `bake.py` | A scripted bake of `program.dsl`, for people who prefer the Text Editor to the sidebar. |
| `noisedeck-export.json` | What was exported, when, against which engine build. |
| `engine/noisemaker_blender.zip` | The add-on. Present if you kept **include engine code** checked. Install this. |
| `shaders/` | Reference copies of the GLSL and shader descriptors behind your effects. Present if you kept **include shader code** checked. |
| `LICENSES/` | Licenses for everything shipped here. |

The add-on renders from its own shader copies inside the archive. The top level `shaders/` folder is
there to read, not to edit: changing a file in it changes nothing.

## Effects used by this program

{{NM_EFFECT_LIST}}

Anything marked with a warning glyph above is not supported by this port and will not render in it,
even though the rest of the program still does. `scope` and `spectrum` are the two the Blender port
excludes outright: they read live audio and MIDI, which the add-on has no host for.

Two more render incorrectly rather than not at all. **bloom** and **lens** are known broken in this
port, and a program using either will bake with those steps wrong while everything else comes out
right. They are still in the supported set because the rest of the program is unaffected.

## The engine

Left **include engine code** checked? The add-on is here, at `engine/noisemaker_blender.zip`.
Install it and bake offline.

Already have the add-on installed? Then you only need `program.dsl`, plus `shaders/` if you kept
**include shader code** checked. Point **DSL File** at it and press **Bake**.

Do not have it at all? Get the port from
<https://github.com/noisefactorllc/noisemaker-for-blender>, build the archive with
`cd blender && zip -r noisemaker_blender.zip noisemaker_blender`, and install that the same way.

Noisedeck exported this program against Noisemaker `{{NM_ENGINE_VERSION}}`. The Blender port is a
second implementation of that engine rather than the same code, so expect small differences from
what the app showed you, on top of the two effects named above.

## License

The Noisemaker engine and the Blender port are MIT licensed; see `LICENSES/`. Your program and the
imagery it renders are yours.
