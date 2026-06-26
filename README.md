# noisemaker-blender

> Run **Noisemaker**'s procedural visuals inside **Blender**.

## What is this?

**Noisemaker** is a procedural visual engine. You write tiny text programs — chains of
effects — and it renders live, animated GPU images:

```
search synth, filter
noise(scaleX: 60).bloom().write(o0)
render(o0)
```

That little language is Noisemaker's **DSL** (a domain-specific language for visuals). The original
engine runs in the browser at [noisedeck.app](https://noisedeck.app).

**noisemaker-blender** runs that same engine *inside Blender* — the same programs and the same ~180
effects, rendered on Blender's GPU. Use it to make textures, materials, and animated backgrounds
from code, with no image files.

One thing worth knowing up front: Blender's compositor can't run custom shader code. So instead of
adding new effect nodes, this addon **bakes** a Noisemaker program into a regular Blender **Image**
(an Image datablock) — which the compositor, any material, or any texture slot can then use like any
other picture.

It is **self-contained**: the addon compiles the DSL and renders it entirely in Blender — no
internet, no Node.js, no separate engine to install.

## What you can do with it

- **Generate animated textures** from a short program — noise, gradients, patterns, color grades,
  blurs, warps.
- **Run simulations on the GPU** — particle/agent systems (flocking, slime/physarum, diffusion),
  fluid (navier–stokes), and 3D volume renders.
- **Use the result anywhere an Image goes** — materials, shader nodes, texture slots, and the
  compositor.
- **Author and bake without leaving Blender** — from the sidebar of the Compositor / Image Editor,
  or from a node in the Noisemaker node editor.

## Requirements

- **Blender 5.1** (uses its bundled **Python 3.13**).
- A **GPU and an open window.** Baking uses Blender's `gpu` module, which needs a real graphics
  context — so it runs in an interactive session, not `--background` (see [Good to know](#good-to-know)).
- Verified on **Apple Silicon / Metal**.

## Install

The addon is a classic single-folder addon, so install it as a zip:

```sh
cd blender && zip -r noisemaker_blender.zip noisemaker_blender
```

Then in Blender: **Edit ▸ Preferences ▸ Add-ons ▸ Install from Disk**, pick
`noisemaker_blender.zip`, and enable **"Noisemaker"**.

(Prefer a live checkout? Symlink `blender/noisemaker_blender` into your Blender `scripts/addons/`
instead.)

## Your first render

1. **Write a program** in Blender's **Text Editor**:
   ```
   search synth, filter
   noise(seed: 1, scaleX: 50, scaleY: 50).adjust().write(o0)
   render(o0)
   ```
2. **Open the Noisemaker panel** — press `N` in the **Compositor** or **Image Editor** and open the
   **Noisemaker** tab, then point it at your text block. (Or add a *Program* node in the
   **Noisemaker** node editor with Shift+A and set its DSL there.)
3. **Click Bake.** The result lands in an Image datablock named `Noisemaker`.
4. **Use it** — add an **Image node** in the compositor pointing at that datablock, or drop the Image
   into any material or texture.

**Every DSL program** has the same shape: name the namespaces it uses (`search synth, filter`),
chain effects, write the result to an output surface (`.write(o0)`), then pick one to show
(`render(o0)`).

Ready-to-bake examples live in [`parity/programs/`](parity/programs). The flagship is
[`parity/programs/north_star.dsl`](parity/programs/north_star.dsl) — a 32-pass program (3D noise →
chaotic particle flow → fluid → color, lighting, and lens).

## Good to know

- **Baking is GUI-only on macOS.** Blender can't draw on the GPU under `--background` on macOS, so a
  window has to be open while baking (it may flash briefly). Headless rendering would need Linux.
- **Output is square** (`size × size`) for now.
- **Audio effects are out of scope** — `scope` and `spectrum` (MIDI / audio input) aren't ported.
  Everything else is. Time-based animation still works.
- **Simulations need time to evolve.** Fluid, agent sims, reaction-diffusion, and cellular automata
  start from nothing, so a single frame looks empty. Raise **Frames** to ~**1800** and set
  **Timestep** ≈ **`0.00167`** (1/600, about 30 s of simulation). Plain still effects want the
  defaults (Frames = 1, Timestep = 0). A long bake takes real time and holds the window.

## Use it in your own Blender project

A bake produces an ordinary Blender **Image** datablock, so it works anywhere a texture does:

- an **Image** node in the compositor,
- an **Image Texture** node in a material or shader,
- any panel that takes an image.

It's stored as **Non-Color** data (raw linear values), so it matches the original engine's output
and isn't double-corrected by color management. Re-bake to refresh it; raise **Frames** to capture an
evolved or animated result.

## What works today

- The **whole 2D effect catalog** (~180 effects across 8 namespaces) renders, and is
  **pixel-identical to the web reference** within 8-bit rounding.
- **Particle/agent sims, fluid (navier–stokes), and the 3D volume renderer** all render and match the
  reference.
- **Chaotic** programs (chaotic agent flows feeding fluid, continuous cellular automata) render
  faithfully and stay stable, but as a *different instance* of the same chaos — they match in look
  and behavior, not pixel-for-pixel.
- **Authoring is end-to-end inside Blender** — the DSL compiler is ported to Python and produces the
  exact same render graph as the reference, so the addon needs no external engine.
- **Audio effects (`scope`, `spectrum`) are out of scope.**

Coverage table, parity numbers, and the full "chaos" explanation: **[STATUS.md](STATUS.md)**,
**[docs/CHAOS-GATE.md](docs/CHAOS-GATE.md)**, and
**[docs/BLENDER-PLATFORM-NOTES.md](docs/BLENDER-PLATFORM-NOTES.md)**.

## How it works

Noisemaker turns a DSL program into a **render graph** — a normalized list of GPU passes. That graph
is the shared seam every Noisemaker port targets. noisemaker-blender ports the whole compiler to
Python (so it runs in-engine) and executes the graph on Blender's `gpu` module. Effect shaders are
translated mechanically from the reference GLSL into the form Blender's Metal backend requires, and
the final image is written to an Image datablock — which is what lets the stock compositor and
material nodes consume it.

→ **[ARCHITECTURE.md](ARCHITECTURE.md)** (how it maps onto Blender) ·
**[PORTING-GUIDE.md](PORTING-GUIDE.md)** (porting a shader) ·
**[docs/GRAPH-JSON-SCHEMA.md](docs/GRAPH-JSON-SCHEMA.md)** (the graph contract).

## Contributing

The addon needs nothing external. The **dev/parity tooling**, however, compares Blender's output
against the reference engine, so it needs a checkout of it via `NM_REFERENCE_ROOT` (default
`../noisemaker`, never vendored):

```sh
NM_BLENDER=<blender> NM_GRADE_PY=<blender-python> bash parity/integration.sh
#   -> end-to-end: DSL → bake → Image datablock, graded byte-exact
```

Full gate commands (compiler, effects, integration) and how to add an effect: **[STATUS.md](STATUS.md)**
and **[PORTING-GUIDE.md](PORTING-GUIDE.md)**. Please also read the
**[Code of Conduct](CODE_OF_CONDUCT.md)**.

## Repo layout

```
blender/noisemaker_blender/   the addon — zip + install this (backend, runtime, shaders, effects, compiler, node tree, UI)
blender/harness/              dev scripts for rendering and compile checks
parity/                       golden-image test harness + DSL programs
tools/                        Node dev tooling (reference graph export, shader/definition conversion)
reference/                    engine specs shared across all Noisemaker ports
ARCHITECTURE.md  PORTING-GUIDE.md  docs/   design, porting rules, platform notes
STATUS.md                     coverage table, parity results, known limits
```

## License

MIT (see [LICENSE](LICENSE)). Use of the Noisemaker and Noise Factor names in derivative products is
subject to the [Trademark Policy](TRADEMARK.md).

Copyright © 2026 Noise Factor LLC
