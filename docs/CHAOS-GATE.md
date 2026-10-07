# The chaos gate

Some programs cannot match the reference engine pixel for pixel on any second shader toolchain:
chaotic agent flows that feed the fluid solver (`points/flow` with `behavior: chaotic`, and the agent
sims that ride the same path) and continuous cellular automata such as lenia and mnca, evolved over
hundreds of frames. They render deterministically and stay bounded in this port, but each engine
produces a different instance of the same chaos. `parity/programs/north_star.dsl` is the flagship
example. These programs are not in the graded parity manifest.

## Why

Blender lowers its GLSL to Metal through its own toolchain; the reference engine runs WebGL2 through
ANGLE. The GLSL specification does not require correctly rounded transcendentals (`pow`, `exp2`,
`log2`, `sin`), so the two toolchains legally differ by about one ULP. A single pass hides that
difference. An iterated or feedback simulation amplifies it:

- The `points/flow` agent steers each agent by the OKLab lightness of the colour it samples
  (`pow(x, 2.4)` in the sRGB-to-linear step, `pow(x, 1/3)` in the cube root). A one-ULP `pow`
  difference is multiplied into the steering angle (×`TAU·kink`) and then forced through two
  per-frame discontinuities, the `fract()` position wrap and the integer `texelFetch` texel
  boundary, so the agent field diverges within a few hundred frames.
- navierStokes then advects the slightly different dye and velocity for the rest of the run: a
  different, equally valid outcome.

## What was tried on Blender

The sibling ports' stabilization mitigations were ported, measured and reverted, because they are
specific to those toolchains:

- The density-cull hi/lo split (`fract(float(id)·φ)` split by radix 4096) fixes a `fract`
  bucketization other toolchains show at about one million agents. Blender's codegen does not have
  that bucketization, so the split moved the result away from the reference instead of toward it.
- Clamping the navierStokes input to [0, 1] made no measured difference.
- The `precise` qualifier is rejected by Blender's shader compiler.
- Rewriting `pow(x, y)` as `exp2(y·log2(x))` cannot change how a toolchain lowers `pow`.

Closing the difference would need a change to Blender's transcendental lowering, which is outside
this port.

## How these programs are checked

The graded manifest (`scripts/parity-summary`) holds deterministic cases, including short stateful
runs of 8 frames. Chaotic programs are checked for stability and character instead: they must
compile, render without NaN or Inf in any pass, stay bounded over the long evolution recipe
(1800 frames at a 1/600 timestep), and show the same structures as the reference.
