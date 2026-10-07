"""Long-bake, cancellation and Image-ownership behavior (GUI mode; self-quits).

Proves these user-facing behaviors:
  ownership   — a bake never resizes or overwrites an existing Image it did not create;
                it bakes to a fresh unique name and reports it. Images a previous bake
                created (marker) are reused/updated as before.
  recovery    — a compile error or an injected mid-render failure leaves every existing
                Image byte-identical, frees the GPU backend, and a following bake succeeds.
  long bake   — a bounded multi-frame bake (60 frames, timestep) completes and its
                per-frame cost is measured and reported.
  cancel      — abandoning a FrameStepper mid-bake (the modal ESC path) writes nothing,
                frees the backend, and a following bake succeeds.
  modal       — bpy.ops.noisemaker.bake('INVOKE_DEFAULT', frames>1) returns
                RUNNING_MODAL and completes asynchronously through the timer loop.

Usage: blender --factory-startup --python blender/harness/test_bake_ownership.py
"""
import os
import sys
import time
import traceback
import types

import bpy
import numpy as np

HARNESS = os.path.dirname(os.path.abspath(__file__))
BLENDER_DIR = os.path.dirname(HARNESS)
ADDON = os.path.join(BLENDER_DIR, "noisemaker_blender")
REPO = os.path.dirname(BLENDER_DIR)
sys.path.insert(0, BLENDER_DIR)

DSL_PATH = os.path.join(REPO, "parity", "programs", "adjust.dsl")
SIZE = 256
TIME = 0.25

fails = []
results = {}


def image_pixels_topdown(img):
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(h, w, 4)[::-1].copy()          # top-down float


def pixels_digest(img):
    arr = image_pixels_topdown(img)
    return (tuple(img.size), np.round(np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8).tobytes())


def make_image(name, w, h, rgba, pack=False):
    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=False)
    arr = np.zeros((h, w, 4), dtype=np.float32)
    arr[..., :] = np.array(rgba, dtype=np.float32) / 255.0
    img.pixels.foreach_set(arr[::-1].reshape(-1))
    img.update()
    if pack:
        img.pack()
    return img


def check(name, cond, detail=""):
    print("  %-6s %s %s" % ("OK" if cond else "FAIL", name, detail))
    if not cond:
        fails.append("%s %s" % (name, detail))
    results[name] = cond


def run_sync_phase():
    import noisemaker_blender
    from noisemaker_blender.ops import bake
    from noisemaker_blender.runtime import pipeline

    noisemaker_blender.register()
    src = open(DSL_PATH).read()

    # --- ownership: foreign image, different size -----------------------------------
    make_image("NM_user_a", 64, 32, (10, 20, 30, 255))
    r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_user_a",
                                size=SIZE, time=TIME)
    fa = bpy.data.images["NM_user_a"]
    nb = bpy.data.images.get("NM_user_a.001")
    expect_a = np.zeros((32, 64, 4), dtype=np.uint8)
    expect_a[..., :] = (10, 20, 30, 255)
    check("ownership-foreign-diff-size", r == {'FINISHED'} and nb is not None
          and tuple(fa.size) == (64, 32) and pixels_digest(fa) == ((64, 32), expect_a.tobytes()),
          "new=%r" % (nb.name if nb else None))
    check("ownership-foreign-unmarked", fa.get("noisemaker_baked") is None
          and (nb is not None and nb.get("noisemaker_baked")))

    # --- ownership: foreign image, same size ----------------------------------------
    make_image("NM_user_b", SIZE, SIZE, (200, 0, 0, 255))
    r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_user_b",
                                size=SIZE, time=TIME)
    fb = bpy.data.images["NM_user_b"]
    digest_b = pixels_digest(fb)
    expect_b = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    expect_b[..., :] = (200, 0, 0, 255)
    nb2 = bpy.data.images.get("NM_user_b.001")
    check("ownership-foreign-same-size", r == {'FINISHED'} and nb2 is not None
          and digest_b == ((SIZE, SIZE), expect_b.tobytes()) and not fb.get("noisemaker_baked"),
          "new=%r" % (nb2.name if nb2 else None))

    # --- ownership: packed foreign image stays packed and untouched ------------------
    fp = make_image("NM_user_packed", 32, 32, (1, 2, 3, 255), pack=True)
    r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_user_packed",
                                size=SIZE, time=TIME)
    expect_p = np.zeros((32, 32, 4), dtype=np.uint8)
    expect_p[..., :] = (1, 2, 3, 255)
    check("ownership-foreign-packed", r == {'FINISHED'} and fp.packed_file is not None
          and tuple(fp.size) == (32, 32) and pixels_digest(fp) == ((32, 32), expect_p.tobytes())
          and bpy.data.images.get("NM_user_packed.001") is not None)

    # --- rebake into our own image reuses it ----------------------------------------
    r1 = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_own",
                                 size=SIZE, time=TIME)
    img1 = bpy.data.images.get("NM_own")
    snap1 = pixels_digest(img1)
    r2 = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_own",
                                 size=SIZE, time=TIME)
    img2 = bpy.data.images.get("NM_own")
    check("rebake-own-reused", r1 == {'FINISHED'} and r2 == {'FINISHED'}
          and img1 is img2 and img2.get("noisemaker_baked")
          and pixels_digest(img2) == snap1 and len(snap1[1]) > 0,
          "same datablock=%r" % (img1 is img2))

    # --- recovery: compile error touches nothing ------------------------------------
    # An operator that reports ERROR/WARNING and returns CANCELLED surfaces as a
    # RuntimeError from the bpy.ops wrapper — treat either surface as CANCELLED.
    def bake_expect_cancel(**kw):
        try:
            return bpy.ops.noisemaker.bake(**kw) == {'CANCELLED'}
        except RuntimeError as e:
            print("    reported: %s" % e)
            return True

    r = bake_expect_cancel(dsl="@@@ not dsl @@@",
                           image_name="NM_user_b", size=SIZE)
    check("recovery-compile-error", r
          and bpy.data.images.get("NM_user_b.002") is None
          and pixels_digest(bpy.data.images["NM_user_b"]) == digest_b)

    # --- recovery: injected mid-render failure frees the backend ---------------------
    from noisemaker_blender.backend import gpu_backend
    from noisemaker_blender.runtime import pipeline as pl

    freed = {"n": 0}

    class SpyBackend(gpu_backend.GpuBackend):
        def free(self):
            freed["n"] += 1
            super().free()

    real_stepper = pl.FrameStepper

    class BoomStepper(real_stepper):
        def step(self):
            if self.frame == 1:                      # fail on the 2nd frame
                raise RuntimeError("injected mid-render failure")
            return super().step()

    real_gb, real_fs = gpu_backend.GpuBackend, pl.FrameStepper
    gpu_backend.GpuBackend, pl.FrameStepper = SpyBackend, BoomStepper
    try:
        r = bake_expect_cancel(dsl=src, image_name="NM_boom",
                               size=SIZE, time=TIME, frames=5, timestep=0.01)
    finally:
        gpu_backend.GpuBackend, pl.FrameStepper = real_gb, real_fs
    check("recovery-render-failure", r and freed["n"] == 1
          and bpy.data.images.get("NM_boom") is None,
          "free calls=%d" % freed["n"])
    # GPU is healthy afterwards: a real bake still succeeds.
    r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_after_fail",
                                size=SIZE, time=TIME)
    check("recovery-gpu-healthy-after-failure", r == {'FINISHED'}
          and bpy.data.images.get("NM_after_fail") is not None)

    # --- bounded long bake (sync path) + timing --------------------------------------
    t0 = time.perf_counter()
    r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_long",
                                size=SIZE, time=TIME, frames=60, timestep=0.01)
    dt = time.perf_counter() - t0
    img = bpy.data.images.get("NM_long")
    check("long-bake-60f", r == {'FINISHED'} and img is not None
          and tuple(img.size) == (SIZE, SIZE),
          "wall=%.2fs ms/frame=%.1f" % (dt, dt / 60 * 1000))
    results["long_bake_ms_per_frame"] = round(dt / 60 * 1000, 1)

    # --- cancel: abandon a FrameStepper mid-bake (the modal ESC path) ----------------
    from noisemaker_blender.compiler import compile_graph
    from noisemaker_blender.runtime import graph_loader
    graph = graph_loader.Graph(compile_graph(src))
    stepper = real_stepper(SpyBackend(os.path.join(ADDON, "shaders", "effects"), SIZE),
                           graph, time=TIME, frames=30, timestep=0.01)
    for _ in range(5):
        stepper.step()
    job = types.SimpleNamespace(error=None, backend=stepper.backend, stepper=stepper,
                                frames=30, requested_name="NM_cancelled")
    job.finish = lambda op, _j=job: bake._BakeJob.finish(_j, op)
    fake_self = types.SimpleNamespace(_job=job, _timer=None)
    fake_self._cleanup = lambda ctx, _s=fake_self: bake.NOISEMAKER_OT_bake._cleanup(_s, ctx)
    bake.NOISEMAKER_OT_bake._release(fake_self, job, bpy.context)
    check("cancel-mid-bake", bpy.data.images.get("NM_cancelled") is None
          and freed["n"] == 2, "free calls=%d" % freed["n"])

    # --- modal cleanup: the timer and status text are cleared on the release paths ---
    removed, cleared = [], []
    fake_ctx = types.SimpleNamespace(
        window_manager=types.SimpleNamespace(
            event_timer_remove=lambda t: removed.append(t)),
        workspace=types.SimpleNamespace(
            status_text_set=lambda s: cleared.append(s)))
    fake_self2 = types.SimpleNamespace(_job=None, _timer="TIMER1")
    fake_self2._cleanup = lambda ctx, _s=fake_self2: bake.NOISEMAKER_OT_bake._cleanup(_s, ctx)
    bake.NOISEMAKER_OT_bake._release(fake_self2, None, fake_ctx)
    check("modal-cleanup-timer-status", removed == ["TIMER1"] and cleared[-1] is None,
          "removed=%r cleared=%r" % (removed, cleared))
    r = bpy.ops.noisemaker.bake('EXEC_DEFAULT', dsl=src, image_name="NM_after_cancel",
                                size=SIZE, time=TIME)
    check("cancel-gpu-healthy-after-cancel", r == {'FINISHED'}
          and bpy.data.images.get("NM_after_cancel") is not None)


def run_modal_phase():
    """Real modal invocations: RUNNING_MODAL now, completion observed via app timer.

    Both entry points are covered: explicit operator frames (the node-tree Bake button
    passes them) and scene settings (the sidebar panels invoke with no overrides, so
    the modal decision must use the RESOLVED frame count, not the raw property).
    """
    src = open(DSL_PATH).read()
    r = bpy.ops.noisemaker.bake('INVOKE_DEFAULT', dsl=src, image_name="NM_modal",
                                size=SIZE, time=TIME, frames=40, timestep=0.01)
    check("modal-invoke-running", r == {'RUNNING_MODAL'},
          "return=%r" % (r,))

    # Scene-configured long bake: no operator overrides at all.
    st = bpy.context.scene.noisemaker
    old_frames = st.frames
    st.frames = 40
    st.timestep = 0.01
    r = bpy.ops.noisemaker.bake('INVOKE_DEFAULT', dsl=src,
                                image_name="NM_modal_scene", size=SIZE, time=TIME)
    st.frames = old_frames
    st.timestep = 0.0
    check("modal-scene-settings-running", r == {'RUNNING_MODAL'},
          "return=%r" % (r,))

    deadline = [time.monotonic() + 300]

    def poll():
        done = (bpy.data.images.get("NM_modal") is not None
                and bpy.data.images.get("NM_modal_scene") is not None)
        if done:
            check("modal-completes", tuple(bpy.data.images["NM_modal"].size) == (SIZE, SIZE)
                  and bpy.data.images["NM_modal"].get("noisemaker_baked")
                  and tuple(bpy.data.images["NM_modal_scene"].size) == (SIZE, SIZE)
                  and bpy.data.images["NM_modal_scene"].get("noisemaker_baked"))
            bpy.ops.wm.quit_blender()
            return None
        if time.monotonic() > deadline[0]:
            check("modal-completes", False,
                  "timed out (modal=%r scene=%r)"
                  % (bpy.data.images.get("NM_modal"), bpy.data.images.get("NM_modal_scene")))
            bpy.ops.wm.quit_blender()
            return None
        return 0.25

    bpy.app.timers.register(poll, first_interval=1.0)


def _t():
    try:
        if bpy.app.background:
            print("GAP005 FAIL: GPU needs GUI mode; run without -b")
        else:
            run_sync_phase()
            print()
            run_modal_phase()
            return None                      # modal phase self-quits via poll()
    except Exception:
        print("GAP005 FAIL (exception):")
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
    return None


if __name__ in ("__main__", "__builtin__", "builtins"):
    bpy.app.timers.register(_t, first_interval=0.5)
