search synth, render
perlin(octaves: 6, ridges: true).pointsEmit(stateSize: x256, layout: grid, seed: 97).pointsRender(density: 36.63, intensity: 96.07, inputIntensity: 0).write(o0)
render(o0)
