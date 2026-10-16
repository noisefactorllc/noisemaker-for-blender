search synth, filter, render
gradient(seed: 2)
  .subchain(name: "feedback", id: "gap004loop") {
    .loopBegin(alpha: 50)
    .adjust(brightness: 1.05)
    .loopEnd()
  }
  .write(o0)
render(o0)
