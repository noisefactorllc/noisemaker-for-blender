# noisemaker-blender

A Blender port of the Noisemaker procedural shader engine — Polymorphic DSL compiler,
render-graph executor, and effects collection — running on Blender's `gpu` module (Metal/Apple).
Sibling to `noisemaker-hlsl` (Unity), `noisemaker-godot`, `noisemaker-td` (TouchDesigner),
`noisemaker-three`, `noisemaker-babylon`.

**Target:** Blender 5.1 · Python 3.13 · Metal / Apple Silicon. Private repo:
`noisefactorllc/noisemaker-blender`.

## What this is (and isn't)

Blender's **compositor cannot host custom GLSL nodes** (a fixed, C-defined node set; Python can't
add to it). So this is **compositor-*feeding***, not compositor-native: effects run via the `gpu`
module offscreen and **bake into Image datablocks** that the real compositor consumes through stock
Image nodes. A custom (`CUSTOM`) node tree + N-panels provide the noisemaker graph UI. See
[`docs/BLENDER-PLATFORM-NOTES.md`](docs/BLENDER-PLATFORM-NOTES.md).

## What works today

- **255 / 257 shader programs compile on Metal** — the whole catalog (184 effects across 8
  namespaces) except the two audio synths `scope`/`spectrum` (audio input is out of scope).
- **End-to-end authoring:** write a DSL program → **Bake** operator → an Image datablock the
  compositor consumes via an Image node. Gated **byte-exact** (`parity/integration.sh`).
- **In-Blender DSL→graph compiler** (`compiler/`, stdlib-only) is **byte-identical** to the
  reference compiler — the addon needs **no external engine** to author or compile.
- **2D effects** (single-pass + stateful), **agents/points** (deposit/billboards), and the
  **3D volume render** namespace are **byte-identical / 1-ULP** to the reference; the full
  19/19-program blaster corpus renders.

## Limitations

- **Chaos gate.** Chaotic agent→navierStokes chains and continuous cellular automata
  (`flow:chaotic`, lenia, mnca, reactionDiffusion) render faithfully, deterministically, and stay
  bounded, but they **do not pixel-match** the reference (full-chain SSIM ~0.0–0.7). Blender's
  GLSL→Metal codegen differs from the reference's ANGLE path by ~1 ULP in transcendentals, which
  iterated/feedback sims amplify (the butterfly effect). Single-pass / 3D / agent-deposit paths
  **are** byte-identical. These programs are graded for *stability and character*, not pixel
  parity — see [`docs/CHAOS-GATE.md`](docs/CHAOS-GATE.md).
- **Audio out of scope:** the media plugin (MIDI / audio inputs) is not ported → `scope`,
  `spectrum` don't compile. Oscillator time-automation still works (it's in the reused pipeline).
- **macOS baking is GUI-only.** Blender raises `SystemError` on any GPU draw under `--background`
  on macOS, so baking needs an interactive session (a window flashes briefly). Headless GPU would
  need Linux.
- **Square output only** (`size × size`); non-square is a future backend enhancement.

## Install & use

The addon renders a Noisemaker DSL program with the `gpu` module and **bakes the result into an
Image datablock** that the real compositor consumes through a stock **Image node**.

1. **Package + install.** It's a legacy `bl_info` addon (no Extension manifest), so install it as a
   zip:
   ```sh
   cd blender && zip -r noisemaker_blender.zip noisemaker_blender
   ```
   Then Edit ▸ Preferences ▸ Add-ons ▸ **Install from Disk** ▸ pick `noisemaker_blender.zip` ▸
   enable **"Noisemaker"**. (Or symlink `blender/noisemaker_blender` into your Blender
   `scripts/addons/`.)
2. **Author** a DSL program in the Text Editor (see [Authoring DSL](#authoring-dsl)), e.g.
   ```
   search synth, filter
   noise(seed: 1, scaleX: 50, scaleY: 50).adjust().write(o0)
   render(o0)
   ```
   (or point the panel at an external `.dsl` file).
3. **Bake** — in the **Compositor** or **Image Editor** sidebar (`N`) ▸ **Noisemaker** tab, pick
   the Text block, set Size/Time, click **Bake**. Or use the **Noisemaker** node editor: add a
   *Program* node (Shift+A), set its DSL + params, and Bake from the node. The result lands in an
   Image datablock (default name `Noisemaker`).
4. **Consume** — add an **Image node** in the compositor pointing at that datablock (or use it as
   any texture). It's stored `Non-Color` (raw linear values, matching the reference capture).

**Stateful effects** (navierStokes, agent sims, reaction-diffusion, cellular automata) need to
*evolve*: raise **Frames** to ~**1800** and set **Timestep** ≈ **`0.00167`** (= 1/600 → ~30 s of
simulation), so the sim reaches steady state. (Frames defaults to 1 — single-pass effects want
Frames=1 / Timestep=0.) `Time` is the animation phase; `Timestep` drives evolution. A 1800-frame
bake takes real time and holds the GUI window.

## Authoring DSL

- A program is a sequence of statements; **`search <namespace>, …` is required first** and must
  precede every effect statement (it makes those effects' names resolvable).
- A chain ends in **`.write(oN)`** to store into one of the output surfaces **`o0`…`o7`**;
  **`render(oN)`** selects which surface is baked. Both a `write()` target and a `search` directive
  are mandatory (the intuitive `noise().adjust()` alone errors). Multi-surface example:
  ```
  search synth, mixer
  noise(seed: 1).write(o0)
  noise(seed: 7, scaleX: 12).write(o1)
  mashup(source: read(o0), layer0_tex: read(o0), layer1_tex: read(o1), layers: 3).write(o2)
  render(o2)
  ```
- The 8 shipped namespaces (184 effects): `classicNoisedeck` (20), `filter` (90), `filter3d` (2),
  `mixer` (15), `points` (10), `render` (11), `synth` (29), `synth3d` (7).
- **Ready-to-bake examples:** [`parity/programs/*.dsl`](parity/programs). The flagship is
  `parity/programs/north_star.dsl` — a 32-pass integration target (3D perlin → chaotic agent flow
  → navierStokes → palette/lighting/lens); `tools/present.py` composites a DSL beside its render.

## Architecture

The universal **render-graph JSON** seam ([`docs/GRAPH-JSON-SCHEMA.md`](docs/GRAPH-JSON-SCHEMA.md))
is the contract. It is produced **either** by the reference compiler (`tools/export-graph.mjs`,
verbatim reference JS) **or** by the addon's in-Blender Python compiler (`compiler/`,
byte-identical) — then consumed by a Python backend on the `gpu` module. Effect GLSL is transpiled
mechanically (`tools/convert-shaders-blender.mjs`) into a `.frag` body + `.createinfo.json`
descriptor (uniforms→push-constants, samplers, output), since Metal requires
`gpu.shader.create_from_info` and forbids inline `uniform`. See [`ARCHITECTURE.md`](ARCHITECTURE.md)
and [`PORTING-GUIDE.md`](PORTING-GUIDE.md).

### Status

| Area | State | Parity |
|---|---|---|
| Shader compile (Metal) | 255 / 257 programs (`scope`/`spectrum` = audio, excluded) | — |
| 2D effects (single-pass + stateful) | whole catalog | byte-identical / ±1 |
| Agents & points (flow/flock/life/deposit/billboards) | render | byte-identical deposit; sims chaos-gated |
| 3D volume render + cubemaps (synth3d × render3d/renderLit3d/cubemap) | render | byte-exact / 1-ULP |
| navierStokes & continuous sims (reactionDiffusion, lenia, mnca) | render | SSIM 0.999 (smooth input); chaos-gated |
| In-Blender DSL→graph compiler | complete | byte-identical to reference |
| Integration surface (bake-to-Image + node tree + N-panels) | complete | byte-exact (`parity/integration.sh`) |
| Blaster corpus (20 programs) | 19/19 renderable (1 non-reference skip) | mostly chaos-gated |

(Per-milestone development history lives in the git log and `docs/IMPLEMENTATION-PLAN.md`.)

## Running the parity gates (contributors)

Dev tooling expects the reference engine at **`$NM_REFERENCE_ROOT`** (default `../noisemaker`,
**not** vendored). Grading uses **Blender's bundled python** (it has numpy; `pip install pillow`
once): `/Applications/Blender.app/Contents/Resources/5.1/python/bin/python3.13`.

```sh
# 1. graph + golden (goldens are byte-identical across ports; reuse a sibling's or mint one)
NM_REFERENCE_ROOT=../noisemaker node tools/export-graph.mjs --file parity/programs/noise.dsl parity/out/noise.graph.json
cp ../noisemaker-godot/parity/out/noise.golden.png parity/out/   # or: parity/export-and-render.mjs

# 2. render candidate (GUI mode — macOS GPU needs a context; self-quits)
NM_JOBS='[{"graph":"parity/out/noise.graph.json","out":"parity/out/noise.candidate.png"}]' \
  blender --factory-startup --python blender/harness/render_all.py
# candidate renders can skip export-graph entirely (in-Blender compiler, no reference):
#   NM_JOBS='[{"dsl":"parity/programs/noise.dsl","out":"parity/out/noise.candidate.png"}]'

# 3. grade
<blender-python> parity/compare.py parity/out/noise.golden.png parity/out/noise.candidate.png --name noise
```

The **DSL compiler** is gated on plain `python3` (stdlib only), comparing the in-addon
`compile_graph` against the reference graph byte-for-byte. `parity/out/` is git-ignored, so seed
the goldens on a fresh clone first:

```sh
NM_REFERENCE_ROOT=../noisemaker bash parity/regen-compiler-goldens.sh   # writes parity/out/<name>.{tokens,ast,compile,expanded,graph}.json
for g in lex parse compile expanded graph; do python3 parity/compiler/check_$g.py; done
```

The **integration surface** (DSL → bake operator → Image datablock) has a one-command end-to-end
gate (it prints a hint if the `adjust` golden needs seeding into `parity/out/`):

```sh
NM_BLENDER=<blender> NM_GRADE_PY=<blender-python> bash parity/integration.sh
```

To add or regenerate an effect, see [`PORTING-GUIDE.md`](PORTING-GUIDE.md).

## Layout

```
reference/            upstream-engine specs (01–10), reused verbatim from noisemaker-hlsl —
                      Unity/HLSL-authored; the backend specs carry directives that don't apply
                      here (see PORTING-GUIDE.md). Do not edit.
docs/                 GRAPH-JSON-SCHEMA, BLENDER-PLATFORM-NOTES, CHAOS-GATE, IMPLEMENTATION-PLAN
tools/                export-graph.mjs, convert-shaders-blender.mjs (GLSL→.frag/.createinfo),
                      convert-defs-blender.mjs (effect-definition JSON), dump-*.mjs, present.py
parity/               compare.py, integration.sh, regen-compiler-goldens.sh, programs/*.dsl,
                      corpus/, compiler/check_*.py, out/ (generated, git-ignored)
blender/
  noisemaker_blender/ the addon: backend/ runtime/ shaders/ effects/ compiler/ nodes/ ops/ props/ ui/
  harness/            spike_*.py (de-risk), compile_check.py, render_all.py, dump_atlas.py
```
