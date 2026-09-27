# {{NM_PROGRAM_NAME}}

A Blender add-on and your program, exported from Noisedeck. Blender's compositor cannot run custom
shader code, so the add-on does not add effect nodes. It **bakes** your program into an ordinary
Blender **Image** datablock, which the compositor, any material and any texture slot can then use
like a picture. It fetches nothing at runtime.

## Install the add-on

1. Unzip this folder anywhere. Leave `engine/noisemaker_blender.zip` zipped: Blender wants the
   archive, not its contents.
2. In Blender, open **Edit > Preferences > Add-ons**. Select **Install from Disk**.
   Select `engine/noisemaker_blender.zip`.
3. Tick **Noisemaker for Blender** in the add-on list to enable it.

You need Blender 5.1 or newer and a working GPU: the add-on renders through Blender's `gpu` module.

## Bake your program

1. Open the **Compositor** or the **Image Editor**. Press **N** to show the sidebar.
   Select the **Noisemaker** tab.
2. Set **Source** to **File**. Point **DSL File** at the `program.dsl` in this folder.
3. Press **Bake**.

The result appears in an Image datablock (named `Noisemaker` unless you change **Image**). Add a stock
**Image** node in the compositor pointing at it, or drop it into any material.

`bake.py` performs the same bake from a script. Open it in Blender's Text Editor. Press **Run Script**.
It reads the `program.dsl` sitting beside it and writes to an Image
called `NoisedeckExport`, with the resolution, frame count and timestep as constants at the top.

### Simulations need time to evolve

Fluid, agent, reaction-diffusion and cellular-automata effects start from an empty state, so a
single frame of one is legitimately blank. For those, raise **Frames** to about **1800** and set
**Timestep** to **0.00167** (1/600): the runtime advances normalized simulation time by one
timestep per frame and wraps it at 1, so that recipe steps the simulation by about 3.0 normalized
time units. Programs made only of still effects want the defaults (**Frames** 1, **Timestep** 0).

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

Two more were previously described as rendering incorrectly. On 2026-09-27 **bloom** and **lens** were
compared against the Noisemaker reference engine's own renders on an Apple-Silicon Blender 5.1 host
(Metal). **bloom** matched the reference engine within this port's published tolerance (worst
per-channel difference 1 in 255 against a tolerance of 2). **lens** renders but carries an open
measured defect: its worst per-channel difference against the reference engine is 10 in 255, above
the published 2-step tolerance, while its structural similarity is 0.99999 — expect small local
differences in lens-heavy programs. Programs that feed such effects through chaotic stateful solvers
(for example a flow → fluid chain) can diverge structurally across engines; that divergence is on
record as an open defect in the add-on repository's compatibility record. The public bake path itself
reproduced the reference engine within tolerance on the checked program. One open item is still on
record: an earlier zero-tolerance comparison against retained historical goldens showed a small bloom
difference (at most 1 in 255) not yet reproduced against the current reference engine; see the add-on
repository's compatibility record. Expect small differences from what the app showed you, on top of
any effect still carrying an open defect.

## The engine

If you kept **include engine code** checked, the add-on is at `engine/noisemaker_blender.zip`.
Install it. Bake offline.

If the add-on is already installed, you only need `program.dsl`, plus `shaders/` if you kept
**include shader code** checked. Point **DSL File** at the program. Press **Bake**.

If you do not have the add-on:

1. Get the port from <https://github.com/noisefactorllc/noisemaker-for-blender>.
2. Build the archive with `cd blender && zip -r noisemaker_blender.zip noisemaker_blender`.
3. Install the archive as described above.

Noisedeck exported this program against Noisemaker `{{NM_ENGINE_VERSION}}`. The Blender port is a
second implementation of that engine rather than the same code, so expect small differences from
what the app showed you.

The archive itself carries its MIT notice as `noisemaker_blender/LICENSE.txt`. The add-on's own
version lives in `engine/noisemaker_blender.zip` (`bl_info` version — visible in Preferences ▸
Add-ons after installing). The kit version (`0.1.N` in this export's file listing) is a kit
publication counter, not the add-on version; the source revision of a published kit is recorded
in its `kit.json` (`source.sha`), which names exactly which add-on the kit contains.

## License

The Noisemaker engine and the Blender port are MIT licensed. See `LICENSES/` (and, inside the
add-on archive, its bundled `LICENSE.txt`). Your program and the imagery it renders are yours.
