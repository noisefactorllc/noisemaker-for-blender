search synth, classicNoisedeck
noise(seed: 1, scaleX: 50, scaleY: 50).write(o0)
gradient(seed: 2).coalesce(tex: read(o0), mix: 50, refractAAmt: 25, refractBAmt: 25).write(o1)
render(o1)
