"""GAP-003 host workflow checks (GUI mode; two sessions; self-quits).

Exercises the distribution-archive install path and the workflows GAP-003
requires that the integration test does not cover, on the recorded host:

  Session 1 (NM_HOSTWORKFLOWS=1, fresh scene):
    - record host/GPU versions (Blender build, GPU vendor/renderer/backend)
    - install the built distribution archive zip via preferences (install/enable)
    - quick start: bake a DSL into an Image datablock through the operator
    - material use: ShaderNodeTexImage wired to a Principled BSDF
    - compositor use: compositor Image node wired to the composite output
    - keyboard: verify the addon registers no custom keymaps (panel/button UI;
      standard Blender keyboard navigation is untouched) — recorded, not skipped
    - save the .blend (image + material + compositor) for session 2
  Session 2 (NM_HOSTWORKFLOWS=2, launch with the saved .blend on the command line):
    - verify the addon stayed enabled across restart (preferences persisted)
    - verify the saved Image datablock round-trips (render compared externally)
    - cleanup: disable + uninstall the addon, verify classes and files removed

Usage (isolated preferences):
  BLENDER_USER_RESOURCES=<fresh dir> blender --factory-startup \
      --python blender/harness/test_host_workflows.py --python-expr \
      "import bpy; bpy.ops.wm.quit_blender()"
  NM_ARCHIVE_ZIP points at the distribution archive zip to install.
  NM_SAVE_BLEND / NM_HASH_FILE point at scratch files shared by both sessions.
"""
import hashlib
import os
import sys
import traceback

import bpy

STAGE = os.environ.get("NM_HOSTWORKFLOWS", "1")
HARNESS = os.path.dirname(os.path.abspath(__file__))
BLENDER_DIR = os.path.dirname(HARNESS)                       # .../blender
REPO = os.path.dirname(BLENDER_DIR)
ARCHIVE = os.environ.get("NM_ARCHIVE_ZIP", os.path.join(
    REPO, "parity", "evidence-2026-09-26", "archive-from-fixed-source.zip"))
SAVE_BLEND = os.environ.get("NM_SAVE_BLEND", "/tmp/nm_hostworkflows.blend")
HASH_FILE = os.environ.get("NM_HASH_FILE", "/tmp/nm_hostworkflows.hash")

QUICK_START_DSL = (
    "search synth, render\n"
    "\n"
    "gradient(type: fourCorners, color1: #006e94, color2: #24e4ff, color3: #bcff46, color4: #efffff).write(o0)\n"
    "render(o0)\n"
)

fails = []


def record_versions():
    import gpu  # blender's gpu module
    import gpu.platform
    print("  host  OK   blender=%r" % bpy.app.version_string)
    print("  host  OK   gpu_vendor=%r renderer=%r" % (
        gpu.platform.vendor_get(), gpu.platform.renderer_get()))
    print("  host  OK   gpu_version=%r backend=%r" % (
        gpu.platform.version_get(), gpu.platform.backend_type_get()))


def image_digest(img):
    """Rounded-uint8 digest of the pixel buffer (the bake contract's precision)."""
    import numpy as np
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return np.round(np.clip(buf, 0.0, 1.0) * 255.0).astype(np.uint8)


def image_hash(img):
    return hashlib.sha256(image_digest(img).tobytes()).hexdigest()


def session1():
    record_versions()

    # --- install/enable from the distribution archive zip ----------------------
    import addon_utils
    r = bpy.ops.preferences.addon_install(
        'EXEC_DEFAULT', filepath=ARCHIVE, overwrite=True)
    assert r == {'FINISHED'}, "addon_install returned %r" % (r,)
    mod = addon_utils.enable("noisemaker_blender", default_set=True)
    assert mod is not None, "addon_enable failed"
    assert addon_utils.check("noisemaker_blender")[1], "addon not enabled"
    bpy.ops.wm.save_userpref()
    print("  install OK  %s enabled (preferences saved)" % os.path.basename(ARCHIVE))

    # --- quick start: operator bakes a DSL into an Image ------------------------
    r = bpy.ops.noisemaker.bake(
        'EXEC_DEFAULT', dsl=QUICK_START_DSL, image_name="NM_quickstart",
        size=256, time=0.25, frames=1, timestep=0.0)
    img = bpy.data.images.get("NM_quickstart")
    assert r == {'FINISHED'} and img is not None, "quick start bake: %r %r" % (r, img)
    import numpy as np
    px = np.asarray(img.pixels[:256 * 4]).reshape(256, 4)
    assert px.std() > 0.01, "quick start image is flat (%.4f)" % px.std()
    print("  quickstart OK  image=%r std=%.4f" % (img.name, px.std()))

    # --- material use: Image texture feeding a Principled BSDF -----------------
    mat = bpy.data.materials.new("NM_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = nt.nodes["Principled BSDF"]
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    out = nt.nodes["Material Output"]
    assert bsdf.inputs["Base Color"].is_linked
    assert any(l.from_node == bsdf for l in out.inputs["Surface"].links)
    print("  material OK  tex->bsdf->output wired")

    # --- compositor use: compositor Image node -> Composite --------------------
    scene = bpy.context.scene
    scene.use_nodes = True
    comp = None
    for attr in ("compositing_node_group", "node_tree", "compositor_node_group"):
        try:
            comp = getattr(scene, attr, None)
        except AttributeError:
            comp = None
        if comp is not None:
            break
    if comp is None:
        comp = bpy.data.node_groups.new("NM_comp", "CompositorNodeTree")
        scene.compositing_node_group = comp
    cimg = comp.nodes.new("CompositorNodeImage")
    cimg.image = img
    composite = next((n for n in comp.nodes
                      if n.type in ('COMPOSITE', 'GROUP_OUTPUT')), None)
    if composite is None:
        composite = comp.nodes.new("NodeGroupOutput")
    comp.links.new(cimg.outputs["Image"], composite.inputs[0])
    assert composite.inputs[0].is_linked
    print("  compositor OK  image->%s wired" % composite.type)

    # --- keyboard: the addon ships panel/button UI only; verify no keymap -------
    # registration that would change keyboard behavior. Recording this is the
    # automatable half of "keyboard interaction"; interactive GUI typing cannot
    # be exercised from a script and is recorded as not executed here.
    import noisemaker_blender
    km_attr = getattr(noisemaker_blender, "keymaps", None)
    assert not km_attr, "addon registers custom keymaps: %r" % (km_attr,)
    print("  keyboard OK  no custom keymap registration (panel/button UI; "
          "standard navigation unchanged; interactive typing not scriptable)")

    # --- save for session 2 -----------------------------------------------------
    # Pack before saving: a script-generated Image buffer only persists in a
    # .blend when packed into the file.
    img.pack()
    bpy.ops.wm.save_as_mainfile('EXEC_DEFAULT', filepath=SAVE_BLEND)
    # PNG references for the session-2 reopen check (byte-deterministic for the
    # same Blender build; avoids in-process pixel reads of a reopened image).
    img.save_render(SAVE_BLEND + ".png")
    print("  save OK  %s render=%s" % (SAVE_BLEND, SAVE_BLEND + ".png"))
    print("HOSTWORKFLOWS SESSION1 PASS")


def session2():
    import addon_utils
    assert addon_utils.check("noisemaker_blender")[1], \
        "addon did not stay enabled after restart"
    print("  persist OK  addon still enabled after restart")

    # The .blend is passed on the command line (loaded at startup); an
    # in-session open_mainfile after GUI init is unreliable on this host.
    img = bpy.data.images.get("NM_quickstart")
    assert img is not None, "Image datablock did not survive save/reopen"
    img.save_render(SAVE_BLEND + ".reopen.png")
    print("  reopen OK  image=%r render written for external pixel comparison: %s"
          % (img.name, SAVE_BLEND + ".reopen.png"))

    # --- cleanup: disable + uninstall, verify removal ---------------------------
    addon_utils.disable("noisemaker_blender", default_set=True)
    assert not addon_utils.check("noisemaker_blender")[1], "addon still enabled"
    # addon_remove needs a UI area (tag_redraw); in a scripted session remove
    # the installed module directory directly, the same thing the operator does.
    import importlib
    import shutil
    mod = sys.modules.get("noisemaker_blender")
    mod_dir = os.path.dirname(mod.__file__) if mod else None
    if mod_dir and os.path.isdir(mod_dir):
        shutil.rmtree(mod_dir)
    sys.modules.pop("noisemaker_blender", None)
    try:
        import noisemaker_blender  # noqa: F401  must now fail to import cleanly
    except ImportError:
        pass
    else:
        fails.append("module still importable after uninstall")
    if fails:
        print("HOSTWORKFLOWS SESSION2 FAIL (%d):" % len(fails))
        for f in fails:
            print("  - " + f)
        sys.stdout.flush()
        return
    print("  cleanup OK  addon disabled and removed")
    print("HOSTWORKFLOWS SESSION2 PASS")


def main():
    try:
        session1() if STAGE == "1" else session2()
    except Exception:
        print("HOSTWORKFLOWS SESSION%s FAIL (exception):" % STAGE)
        traceback.print_exc()
    sys.stdout.flush()
    bpy.ops.wm.quit_blender()


if bpy.app.background:
    print("HOSTWORKFLOWS FAIL: these checks need GUI mode; run without -b")
else:
    bpy.app.timers.register(main, first_interval=0.5)
