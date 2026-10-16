search synth, classicNoisedeck
noise(seed: 1, scaleX: 50, scaleY: 50).write(o0)
gradient(seed: 2).composite(tex: read(o0), blendMode: mix, mix: 50).write(o1)
render(o1)
