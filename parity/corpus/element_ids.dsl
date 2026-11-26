search synth, filter, synth3d
noise(_id: "pond").invert(_id: "flip").write(o1, _id: "out")
read(surface: o1, _id: "again").write(o0)
noise3d().write3d(vol0, geo0, _id: "volume")
read3d(tex3d: vol0, geo: geo0, _id: "readVolume").write(o2)
render(o0)
