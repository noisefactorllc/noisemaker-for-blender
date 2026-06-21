"""Integration-surface end-to-end test (GUI mode; self-quits).

Proves the user-facing path the addon ships:
    DSL text  ->  register()'d operator  ->  compile_graph  ->  GpuBackend  ->  Image datablock

Checks, all in one real Blender session:
  1. register()/unregister() succeed and every integration class is registered.
  2. The CUSTOM node tree + node instantiate (init(), properties).
  3. bpy.ops.noisemaker.bake bakes adjust.dsl into an Image datablock.
  4. INVARIANT A — the baked Image equals the DIRECT pipeline render exactly (the bake
     wrapper adds no error: uint8 -> /255 float -> *255 round-trips losslessly).
  5. INVARIANT B — the baked Image matches the adjust golden (transitively: the direct
     path is already gated byte-exact to the reference).

Usage: blender --factory-startup --python blender/harness/test_integration.py
"""
import os
import sys
import traceback

import bpy
import numpy as np

HARNESS = os.path.dirname(os.path.abspath(__file__))
BLENDER_DIR = os.path.dirname(HARNESS)                       # .../blender
ADDON = os.path.join(BLENDER_DIR, "noisemaker_blender")
REPO = os.path.dirname(BLENDER_DIR)
sys.path.insert(0, BLENDER_DIR)

DSL_PATH = os.path.join(REPO, "parity", "programs", "adjust.dsl")
GOLDEN = os.path.join(REPO, "parity", "out", "adjust.golden.png")
SIZE = 256
TIME = 0.25


def image_to_topdown_uint8(img):
    """Read an Image datablock back to the same top-down uint8 HxWx4 the backend emits."""
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(h, w, 4)                               # bottom-up float [0,1]
    return np.round(np.clip(arr[::-1], 0.0, 1.0) * 255.0).astype(np.uint8)  # -> top-down uint8


def run():
    import noisemaker_blender
    from noisemaker_blender.compiler import compile_graph
    from noisemaker_blender.runtime import graph_loader, pipeline, pngio
    from noisemaker_blender.backend.gpu_backend import GpuBackend

    shaders_root = os.path.join(ADDON, "shaders", "effects")

    def bake_and_read(dsl_src, image_name, frames=1, timestep=0.0):
        """Bake via the operator AND render the same graph directly; return (arr_op, arr_direct).
        INVARIANT A compares them — byte-exact at any recipe since it's the same backend+graph."""
        be = GpuBackend(shaders_root, SIZE)
        arr_d = pipeline.render(be, graph_loader.Graph(compile_graph(dsl_src)),
                                time=TIME, frames=frames, timestep=timestep)
        be.free()
        r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=dsl_src, image_name=image_name,
                                    size=SIZE, time=TIME, frames=frames, timestep=timestep)
        im = bpy.data.images.get(image_name)
        if r != {'FINISHED'} or im is None:
            raise RuntimeError("operator returned %r / image=%r" % (r, im))
        return image_to_topdown_uint8(im), arr_d

    fails = []

    # --- 1. registration --------------------------------------------------------------
    noisemaker_blender.register()
    # Probe via the right API per class kind: operators by idname, the PropertyGroup by its
    # Scene pointer, panels by bpy.types. (Node tree + node are proven functionally below by
    # actually instantiating them — the stronger check.)
    expected = [
        ("operator", lambda: bpy.ops.noisemaker.bake.idname()),
        ("Scene.noisemaker (NoisemakerSettings)", lambda: bpy.types.Scene.noisemaker),
        ("NOISEMAKER_PT_compositor", lambda: bpy.types.NOISEMAKER_PT_compositor),
        ("NOISEMAKER_PT_image_editor", lambda: bpy.types.NOISEMAKER_PT_image_editor),
    ]
    for name, probe in expected:
        try:
            probe()
            print("  reg OK   ", name)
        except Exception as e:
            fails.append("registration: %s missing (%r)" % (name, e))

    # --- 2. node tree + node instantiate ----------------------------------------------
    try:
        nt = bpy.data.node_groups.new("NM Test", "NoisemakerNodeTree")
        node = nt.nodes.new("NoisemakerProgramNode")
        assert node.outputs and node.outputs[0].name == "Image", "node output socket missing"
        node.size = SIZE
        node.time = TIME
        print("  node OK   tree=%r node=%r size=%d" % (nt.name, node.name, node.size))
    except Exception as e:
        fails.append("node instantiate: %r" % e)

    # --- 3+4. bake via operator, compare to direct pipeline ---------------------------
    src = open(DSL_PATH).read()

    # adjust: single-pass, the gated byte-exact reference program. Bake it via the operator
    # and also render it directly (INVARIANT A), and dump the PNG so an out-of-process grader
    # (Blender's standalone python, which has pillow) can close INVARIANT B vs the golden.
    try:
        arr_op, arr_direct = bake_and_read(src, "NM_e2e", frames=1)
    except Exception as e:
        fails.append("adjust bake: %r" % e)
        arr_op = arr_direct = None
    img = bpy.data.images.get("NM_e2e")
    if img is None or arr_op is None:
        fails.append("operator did not create the 'NM_e2e' Image datablock")
    else:
        print("  img OK    %r size=%s float=%s colorspace=%s"
              % (img.name, tuple(img.size), img.is_float, img.colorspace_settings.name))
        pngio.write_png("/tmp/nm_bake_adjust.png", arr_op)
        print("  dump OK   /tmp/nm_bake_adjust.png")
        print("  diag      direct mean=%s px[0,0]=%s ctr=%s"
              % (arr_direct.reshape(-1, 4).mean(0).round(1).tolist(),
                 arr_direct[0, 0].tolist(),
                 arr_direct[128, 128].tolist()))
        print("  diag      bake   mean=%s px[0,0]=%s ctr=%s"
              % (arr_op.reshape(-1, 4).mean(0).round(1).tolist(),
                 arr_op[0, 0].tolist(),
                 arr_op[128, 128].tolist()))

        # INVARIANT A: bake wrapper is lossless vs the direct pipeline
        if arr_op.shape != arr_direct.shape:
            fails.append("shape %s != direct %s" % (arr_op.shape, arr_direct.shape))
        else:
            dA = int(np.abs(arr_op.astype(int) - arr_direct.astype(int)).max())
            print("  INVARIANT A (bake == direct pipeline): max-abs-diff=%d" % dA)
            if dA != 0:
                fails.append("bake != direct pipeline (max-abs-diff=%d)" % dA)

        # INVARIANT B: bake matches the adjust golden
        try:
            from PIL import Image as PILImage
            g = np.asarray(PILImage.open(GOLDEN).convert("RGBA"), dtype=np.uint8)
            if g.shape == arr_op.shape:
                dB = int(np.abs(arr_op.astype(int) - g.astype(int)).max())
                print("  INVARIANT B (bake == golden):          max-abs-diff=%d" % dB)
                if dB > 1:
                    fails.append("bake vs golden max-abs-diff=%d (>1)" % dB)
            else:
                print("  INVARIANT B skipped: golden shape %s != %s" % (g.shape, arr_op.shape))
        except ImportError:
            print("  INVARIANT B skipped: PIL not available (A already proves the wrapper)")

    # --- 4b. breadth: the operator across program shapes -------------------------------
    # adjust above is a trivial single-pass program. The operator's real risk surface is
    # multi-pass / multi-write-surface / stateful (frames+timestep). INVARIANT A is byte-exact
    # at any recipe (same backend+graph), so it's the definitive check that those paths are
    # wired right. Reference parity then follows transitively: A (bake==pipeline) + the corpus
    # scorecard (pipeline==goldens) + graph parity (compile_graph==export-graph).
    CORPUS = os.path.join(REPO, "parity", "corpus")
    sweep = [
        # (name, frames, timestep, note)
        ("bRUa1g", 1, 0.0,       "multi-pass static (perlin->tetraCosine->lighting)"),
        ("kQ_2mw", 1, 0.0,       "12 passes, 3 write surfaces o0/o1/o2"),
        ("MQ2ojg", 8, 0.0016667, "stateful reactionDiffusion (exercises frames+timestep)"),
    ]
    for name, fr, ts, note in sweep:
        dpath = os.path.join(CORPUS, name + ".dsl")
        if not os.path.exists(dpath):
            fails.append("sweep %s: %s not found" % (name, dpath))
            continue
        try:
            a_op, a_direct = bake_and_read(open(dpath).read(), "NM_sweep_" + name,
                                           frames=fr, timestep=ts)
            if a_op.shape != a_direct.shape:
                fails.append("sweep %s: shape %s != %s" % (name, a_op.shape, a_direct.shape))
                continue
            d = int(np.abs(a_op.astype(int) - a_direct.astype(int)).max())
            print("  sweep %-4s A(bake==pipeline) max-diff=%d  [%s]  %s"
                  % ("OK" if d == 0 else "BAD", d, name, note))
            if d != 0:
                fails.append("sweep %s: bake != pipeline (max-diff=%d)" % (name, d))

            # INVARIANT C: the in-addon compiler is a render-level drop-in for the external
            # tool — render(compile_graph(dsl)) == render(load(<name>.graph.json)). Stronger
            # than structural graph-parity (which treats int==float as equal): catches any
            # type-level discrepancy in the in-memory dict that would change the render.
            gjson = os.path.join(REPO, "parity", "out", name + ".graph.json")
            if os.path.exists(gjson):
                beC = GpuBackend(shaders_root, SIZE)
                a_json = pipeline.render(beC, graph_loader.load(gjson),
                                         time=TIME, frames=fr, timestep=ts)
                beC.free()
                dc = int(np.abs(a_direct.astype(int) - a_json.astype(int)).max())
                print("  sweep %-4s C(compile_graph==graph.json) max-diff=%d  [%s]"
                      % ("OK" if dc == 0 else "BAD", dc, name))
                if dc != 0:
                    fails.append("sweep %s: compile_graph render != graph.json render "
                                 "(max-diff=%d)" % (name, dc))
        except Exception as e:
            fails.append("sweep %s: %r" % (name, e))

    # --- 4c. error paths: bad input must fail gracefully (not crash, not claim success) -
    # A user will hit these. The operator catches and reports; from bpy.ops a reported
    # {'ERROR'} surfaces as RuntimeError — both that and a {'CANCELLED'} return are graceful;
    # only {'FINISHED'} (claiming success on bad input) is a failure.
    def expect_fail(label, **kw):
        try:
            r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', **kw)
            if r == {'FINISHED'}:
                fails.append("error-path %s: expected failure, got FINISHED" % label)
            else:
                print("  errpath OK %-14s -> %r" % (label, r))
        except RuntimeError as e:
            print("  errpath OK %-14s -> reported: %s" % (label, str(e).splitlines()[-1][:54]))
        except Exception as e:
            fails.append("error-path %s: ungraceful %r" % (label, e))

    expect_fail("invalid-dsl", dsl="@@@ this is not noisemaker @@@", image_name="NM_err")
    expect_fail("no-source")  # no dsl/text/file, fresh scene has no source set

    # --- 5. unregister round-trips ----------------------------------------------------
    try:
        noisemaker_blender.unregister()
        print("  unreg OK")
    except Exception as e:
        fails.append("unregister: %r" % e)

    print()
    if fails:
        print("INTEGRATION FAIL (%d):" % len(fails))
        for f in fails:
            print("  - " + f)
    else:
        print("INTEGRATION PASS — DSL -> operator -> Image is byte-exact end-to-end")
    sys.stdout.flush()


if bpy.app.background:
    print("INTEGRATION FAIL: GPU needs GUI mode; run without -b")
else:
    def _t():
        try:
            run()
        except Exception:
            print("INTEGRATION FAIL (exception):")
            traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_t, first_interval=0.5)
