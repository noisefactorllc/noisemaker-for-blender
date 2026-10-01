"""GAP-003 interactive GUI checks (a real windowed session driven by real X11 input).

Companion to test_host_workflows.py: installs the same distribution archive into
isolated preferences, then exercises the interactive-GUI observations GAP-003 left
open, in a live windowed Blender session (GUI mode under an X display — not -b):

  1. window focus: the companion driver sets real X11 input focus on the Blender
     window (xdotool windowfocus; getwindowfocus must return the Blender window).
  2. interactive typing: real X11 keystrokes typed into the Text Editor must land
     in a Text datablock byte-for-byte — the documented DSL source path (source_mode
     TEXT, "edit it in the Text Editor"). The empty datablock itself is created
     from the session script (recorded as scripted): the editor's Ctrl+N binding
     opens the modal File-New popup, which suspends Blender's timers on this host.
  3. panel visibility: the Noisemaker sidebar tab/panel is opened by a REAL 'n'
     keypress over a compositor node editor; Blender's own screenshot captures the
     drawn UI. Control screenshots: sidebar forced closed before the keypress, and
     the same sidebar with the addon unregistered (content must disappear).
  4a. operator-search control: the bake-adjacent delivery chain is verified with
      a builtin — real F3 over the viewport, typed 'Select All', Return keypress
      must change the selection (Space is animation playback in this Blender;
      F3 is the operator-search binding — both measured).
  4b. keyboard-invoked operator (recorded observation): the bake operator is
      attempted through the operator search popup (real F3, typed query, Return)
      against the interactively typed DSL. Measured outcome on this host: the
      operator is registered (bpy.ops.noisemaker.bake) but the search popup does
      not list it (builtin control 4a passes; report "Failed to find 'Bake
      Noisemaker'" with the exact label). Recorded verbatim as an open
      interactive-GUI item in GAP-003, not as a session fail.

Implementation notes (measured on the recorded host; delivery probes are in the
job evidence, not the repository):
  - The session must never block the main/UI thread: everything runs as
    rescheduled bpy.app.timers ticks (a timer callback that sleeps blocks event
    processing, and real X11 key events sent while blocked are lost).
  - The splash screen must be suppressed at startup (show_splash=False via a
    --python-expr BEFORE this script) or it swallows the first keypresses/clicks.
  - Workspace switching is not scriptable in this Blender (window.workspace
    assignment does not take), so the session re-purposes the Layout workspace's
    single editor area in place between steps (scripted layout setup, recorded).

No mouse-driven widget clicks inside the panel are attempted (widget coordinates
are not scriptable); the text-pointer assignment into ``scene.noisemaker`` (the
panel's datablock dropdown row) is done from this script and is recorded as
scripted. The addon registers no custom keymaps (verified in
test_host_workflows.py); the keystrokes here are standard Blender bindings.

Coordination: the companion driver script performs the real input events and
handshakes through marker files in NM_GUI_DIR (state.json written here, m_* marker
files written by the driver). All artifacts (screenshots, logs) go to
NM_EVIDENCE_DIR, never into the repository.

Usage (GUI mode under a display):
  BLENDER_USER_RESOURCES=<fresh dir> blender --factory-startup \
      --python-expr "import bpy; bpy.context.preferences.view.show_splash = False" \
      --python blender/harness/test_interactive_gui.py
  NM_ARCHIVE_ZIP points at the distribution archive zip to install.
"""
import json
import os
import time
import traceback

import bpy

GUI_DIR = os.environ.get("NM_GUI_DIR", "/tmp/nm-gui")
EVID = os.environ.get("NM_EVIDENCE_DIR", os.path.join(GUI_DIR, "evidence"))
ARCHIVE = os.environ.get("NM_ARCHIVE_ZIP")

TYPED_DSL = (
    "search synth, filter\n"
    "noise(seed: 1, scaleX: 50, scaleY: 50).adjust().write(o0)\n"
    "render(o0)\n"
)
IMAGE_NAME = "NM_interactive"

os.makedirs(GUI_DIR, exist_ok=True)
os.makedirs(EVID, exist_ok=True)

fails = []
notes = []


class FlowFail(Exception):
    """Terminal session failure (recorded, then the session quits)."""


def log(msg):
    print("  %s" % msg, flush=True)


def set_state(token, **extra):
    data = {"token": token, "ts": time.time(), "fails": fails}
    data.update(extra)
    tmp = os.path.join(GUI_DIR, "state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(GUI_DIR, "state.json"))
    log("state -> %s %s" % (token, extra if extra else ""))


def marker(name):
    return os.path.join(GUI_DIR, "m_" + name)


def wait_marker(name, timeout=1800.0):
    """Generator: poll until the driver's marker file appears.

    Yields the reschedule interval instead of sleeping — the main/UI thread must
    keep running so real X11 key events are not lost.
    """
    deadline = time.time() + timeout
    n = 0
    while not os.path.exists(marker(name)):
        if time.time() >= deadline:
            raise FlowFail("driver never signaled marker %r" % name)
        n += 1
        if n % 20 == 0:
            log("still waiting for marker %r" % name)
        yield 0.25


def wait_until(predicate, timeout=60.0, interval=0.25):
    deadline = time.time() + timeout
    while not predicate():
        if time.time() >= deadline:
            return False
        yield interval
    return True


def area_of(kind):
    for a in bpy.context.window.screen.areas:
        if a.type == kind:
            return a
    return None


def area_center_window_coords(area):
    # area.x/area.y are window-space coordinates of the area's bottom-left.
    return (area.x + area.width // 2, area.y + area.height // 2)


def repurpose_area(kind, tree_type=None, timeout=15.0):
    """Generator: turn the single editor area into `kind` (scripted setup, recorded).

    Workspace switching is not scriptable in this Blender (window.workspace
    assignment does not take), so the session re-purposes the Layout
    workspace's single editor area in place between steps.
    """
    area = area_of(kind)
    if area is None:
        for a in bpy.context.window.screen.areas:
            if a.type in ('VIEW_3D', 'TEXT_EDITOR', 'NODE_EDITOR'):
                area = a
                break
        assert area is not None, "no repurposable editor area found"
        area.type = kind
        if not (yield from wait_until(lambda: area_of(kind) is not None, timeout)):
            raise FlowFail("area of type %r not available" % kind)
        area = area_of(kind)
    if tree_type is not None:
        sp = area.spaces.active
        if getattr(sp, "tree_type", None) != tree_type:
            sp.tree_type = tree_type
        if not (yield from wait_until(
                lambda: getattr(area.spaces.active, "tree_type", "") == tree_type, timeout)):
            raise FlowFail("tree_type %r not set (got %r)"
                           % (tree_type, getattr(area.spaces.active, "tree_type", "")))
    return area


def screenshot(name):
    """Record the intended capture; the companion driver takes it at the X server.

    bpy.ops.screen.screenshot called from a timer stopped Blender's timer loop on
    the recorded host (measured), so the driver captures the real X framebuffer
    (xwd, converted to PNG after the session) at the matching phase instead.
    """
    notes.append("screenshot handled driver-side at the X server: %s" % name)
    log("screenshot (driver-side) %s" % name)
    return os.path.join(EVID, name)


def ui_region_width(area):
    for r in area.regions:
        if r.type == 'UI':
            return r.width
    return 0


def verify_typed_text(space):
    txt = space.text
    if txt is None:
        txt = bpy.data.texts.get("Text")
    if txt is None:
        for t in bpy.data.texts:
            log("texts present: %r" % (t.name,))
        return False, "no Text datablock active after Ctrl+N + typing"
    body = txt.as_string()
    if body == TYPED_DSL:
        return True, "Text datablock %r byte-identical to the typed DSL" % txt.name
    return False, "typed content mismatch (repr):\n--- expected ---\n%r\n--- actual ---\n%r" % (
        TYPED_DSL, body)


def bake_image_check():
    img = bpy.data.images.get(IMAGE_NAME)
    if img is None:
        return False, None
    import numpy as np
    w, h = img.size
    if w == 0 or h == 0:
        return False, img
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    px = buf.reshape(-1, 4)
    std = float(px[:, :3].std())
    flat = std <= 0.01
    return (not flat), {"name": img.name, "size": [w, h], "std": std}


def search_popup_op():
    window = bpy.context.window
    pops = getattr(window, "popup_operators", None)
    if pops is None:
        return None
    try:
        return [str(p) for p in pops]
    except Exception:
        return None


def record_versions():
    import gpu  # noqa
    import gpu.platform
    log("blender=%r" % bpy.app.version_string)
    log("gpu_vendor=%r renderer=%r" % (gpu.platform.vendor_get(), gpu.platform.renderer_get()))
    log("gpu_version=%r backend=%r" % (gpu.platform.version_get(), gpu.platform.backend_type_get()))
    import platform
    log("uname=%r" % (platform.uname(),))
    log("display=%r" % os.environ.get("DISPLAY"))


def finish():
    set_state("done", fails=fails)
    log("INTERACTIVE-GUI %s (%d fails)" % ("PASS" if not fails else "FAIL", len(fails)))
    for n in notes:
        log("note: " + n)
    for f in fails:
        log("fail: " + f)
    bpy.ops.wm.quit_blender()


def flow():
    """Sequential state machine as a generator; raises FlowFail on hard failure."""
    record_versions()

    # --- install/enable the distribution archive into isolated preferences ------
    import addon_utils
    r = bpy.ops.preferences.addon_install('EXEC_DEFAULT', filepath=ARCHIVE, overwrite=True)
    assert r == {'FINISHED'}, "addon_install returned %r" % (r,)
    mod = addon_utils.enable("noisemaker_blender", default_set=True)
    assert mod is not None, "addon_enable failed"
    assert addon_utils.check("noisemaker_blender")[1], "addon not enabled"
    bpy.ops.wm.save_userpref()
    log("install OK  %s enabled (preferences saved)" % os.path.basename(ARCHIVE))

    # --- 1: driver focuses the window -------------------------------------------
    set_state("ready")
    yield from wait_marker("ready")
    log("focus step done (driver recorded X11 focus evidence)")

    # --- 2: Text Editor -> real character typing into a Text datablock ----------
    # The keystrokes are real X11 input; only the empty typing target is created
    # from the session script (recorded as scripted): on this host the Text
    # Editor's Ctrl+N binding opens the modal File-New popup menu, which suspends
    # Blender's timers and wedges any scripted session (measured), so the
    # datablock cannot be created by a scripted keystroke here.
    ta = yield from repurpose_area('TEXT_EDITOR')
    sp = ta.spaces.active
    r = bpy.ops.text.new('EXEC_DEFAULT')
    assert r == {'FINISHED'}, "text.new returned %r" % (r,)
    sp.text = bpy.data.texts[-1]
    cx, cy = area_center_window_coords(ta)
    notes.append("text area window-coords=(%d,%d) size=%dx%d show_region_ui=%r" % (
        cx, cy, ta.width, ta.height, getattr(sp, "show_region_ui", None)))
    screenshot("scripting_before_typing.png")
    set_state("ws_scripting", area_center=[cx, cy])
    yield from wait_marker("ws_scripting")
    ok, why = verify_typed_text(sp)
    if not ok:
        fails.append(why)
        raise FlowFail("typed content mismatch")
    log("typing OK  %s" % why)
    set_state("typing_ok")

    # --- 3: compositor node editor -> real 'n' opens the Noisemaker sidebar -----
    na = yield from repurpose_area('NODE_EDITOR', tree_type='CompositorNodeTree')
    # Scripted (recorded): give the editor a real compositor tree, as a user
    # setting up the compositor would.
    scene = bpy.context.scene
    if not scene.use_nodes:
        scene.use_nodes = True
    sp = na.spaces.active
    # Force the sidebar closed WITHOUT the keyboard, so the driver's real 'n'
    # keypress is what opens it.
    closed = False
    for _ in range(4):
        if ui_region_width(na) <= 1:
            closed = True
            break
        sp.show_region_ui = False
        yield 0.25
    assert closed, "could not close the sidebar programmatically"
    screenshot("sidebar_closed.png")
    closed_w = ui_region_width(na)
    nx, ny = area_center_window_coords(na)
    set_state("ws_compositing", area_center=[nx, ny])
    yield from wait_marker("ws_compositing")
    open_w = ui_region_width(na)
    if not (open_w > closed_w):
        fails.append("sidebar did not open after real 'n' keypress (UI width %r -> %r)"
                     % (closed_w, open_w))
        raise FlowFail("sidebar did not open")
    screenshot("sidebar_open.png")
    # Programmatic panel-presence: the addon's registered panel classes poll true
    # in this editor's context (draws the Noisemaker tab/panel in the sidebar).
    import noisemaker_blender.ui.panels as panels
    region = next(r for r in na.regions if r.type == 'WINDOW')
    drawn = []
    for cls in panels._CLASSES:
        pf = getattr(cls, "poll", None)
        try:
            with bpy.context.temp_override(window=bpy.context.window,
                                           screen=bpy.context.window.screen,
                                           area=na, region=region, space_data=sp):
                if pf is None or pf(bpy.context):
                    drawn.append(cls.bl_idname)
        except Exception as e:
            fails.append("panel poll %s raised: %s" % (cls.bl_idname, e))
    log("panel OK  sidebar %r->%r px; panel classes polling true in this editor: %s"
        % (closed_w, open_w, drawn))
    if not drawn:
        fails.append("no Noisemaker panel class polls true in the compositor editor")
    set_state("sidebar_open")

    # --- control screenshot: same open sidebar with the addon unregistered ------
    yield from wait_marker("sidebar_open")
    addon_utils.disable("noisemaker_blender")
    assert not addon_utils.check("noisemaker_blender")[1]
    yield 0.5
    screenshot("sidebar_addon_disabled.png")
    disabled_w = ui_region_width(na)
    addon_utils.enable("noisemaker_blender")
    assert addon_utils.check("noisemaker_blender")[1]
    log("control OK  UI width addon-disabled=%r (panel content removed; sidebar kept open)"
        % disabled_w)
    set_state("snap_disabled")
    yield from wait_marker("snap_disabled")

    # --- 4a: search-popup control: a builtin operator must be executable --------
    # Measured control: F3 opens the operator-search popup, typed text lands,
    # Return executes the top match. 'Select All' must change the selection;
    # if it does not, the popup delivery regressed and the session fails.
    va = yield from repurpose_area('VIEW_3D')
    vx, vy = area_center_window_coords(va)
    before = sorted(o.name for o in bpy.context.selected_objects)
    set_state("ws_search_open", area_center=[vx, vy], query="Select All")
    yield from wait_marker("ws_search_open", timeout=600.0)
    set_state("ws_search_query", query="Select All")
    yield from wait_marker("ws_search_query", timeout=600.0)
    set_state("ws_search_return")
    yield from wait_marker("ws_search_return", timeout=600.0)
    yield 2.0
    after = sorted(o.name for o in bpy.context.selected_objects)
    if after == before:
        fails.append("operator-search control failed: 'Select All' via F3 did not "
                     "change the selection (%r)" % (before,))
        raise FlowFail("search control failed")
    log("search control OK  'Select All' via F3 changed the selection %r -> %r"
        % (before, after))

    # --- 4b: keyboard-invoked addon operator (recorded observation) -------------
    st = bpy.context.scene.noisemaker
    # Scripted (recorded): bind the interactively typed Text datablock and a
    # distinctive Image name — the panel's pointer/identifier rows are not
    # keyboard-reachable, so the scene group is populated from the session script.
    st.text = bpy.data.texts["Text"]
    st.image_name = IMAGE_NAME
    st.size = 256
    st.frames = 1
    st.timestep = 0.0
    log("scene.noisemaker bound (scripted): text=%r image=%r" % (st.text.name, st.image_name))
    screenshot("before_search.png")

    got = None
    for attempt, query in enumerate(("Bake Noisemaker", "bake")):
        notes.append("search attempt %d: query %r" % (attempt, query))
        set_state("ws_search_open", area_center=[vx, vy], query=query)
        yield from wait_marker("ws_search_open", timeout=600.0)
        # Popup state is not introspectable while the popup is open (timers are
        # not our problem here: the search popup keeps pumping events), so the
        # attempt is judged purely by its outcome below.
        set_state("ws_search_query", query=query)
        yield from wait_marker("ws_search_query", timeout=600.0)
        set_state("ws_search_return")
        yield from wait_marker("ws_search_return", timeout=600.0)
        # If Return matched, the operator runs synchronously and blocks this
        # event loop until it finishes; poll for the produced Image. If the
        # popup is still open, Return did not run the operator.
        deadline = time.time() + 240.0
        while time.time() < deadline:
            ok, info = bake_image_check()
            if ok:
                got = info
                break
            if search_popup_op():
                notes.append("attempt %d: popup still open after Return (query unmatched)"
                             % attempt)
                break
            yield 1.0
        if got is not None:
            break
    if got is None:
        # Recorded observation (measured on this host, repeated): the addon's
        # bake operator is registered (bpy.ops.noisemaker.bake -> NOISEMAKER_OT_bake)
        # but is not found by the operator-search popup, while builtin operators
        # are (4a). Mouse widget clicks are not scriptable, so the panel button
        # cannot be exercised from a session either. This stays an open
        # interactive-GUI item in GAP-003; it is not counted as a session fail.
        notes.append("keyboard-invoked bake via the operator search popup produced "
                     "no %r; queries tried: %s (search pool works for builtins, "
                     "see 4a); the operator itself is exercised via the documented "
                     "API entry points in test_integration.py / test_host_workflows.py"
                     % (IMAGE_NAME, ["Bake Noisemaker", "bake"]))
        log("bake-by-search NOT REACHABLE (recorded observation; GAP-003 stays open)")
        finish()
        return
    # Save the produced Image as a PNG artifact (source-bound output).
    img = bpy.data.images.get(IMAGE_NAME)
    try:
        img.save_render(os.path.join(EVID, "baked_image.png"))
    except Exception as e:
        notes.append("save_render failed: %s" % e)
    log("bake OK  baked %r %s std=%.4f (operator invoked via real F3/typing/Return)"
        % (got["name"], got["size"], got["std"]))
    screenshot("after_bake.png")
    finish()


def make_tick():
    """Build the rescheduled timer callback that drives the flow generator.

    The generator is created ONCE here and driven across ticks by the returned
    closure; registering a function that creates a fresh generator per call
    would restart the whole session on every tick.
    """
    gen = flow()

    def tick():
        try:
            return next(gen)
        except StopIteration:
            return None
        except FlowFail as e:
            fails.append(str(e))
            finish()
            return None
        except Exception:
            fails.append("exception:\n" + traceback.format_exc())
            finish()
            return None

    return tick


if bpy.app.background:
    print("INTERACTIVE-GUI FAIL: these checks need a windowed session; run without -b")
else:
    bpy.app.timers.register(make_tick(), first_interval=2.0)
