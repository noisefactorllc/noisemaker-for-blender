"""GAP-003 macOS real-input interactive leg (windowed session + companion driver).

The macOS counterpart of test_interactive_gui.py. GAP-003's real-input
interactive leg (install from the distribution zip, open the Noisemaker tab,
type a DSL program into the Text datablock with real keystrokes, click the
Bake button, confirm a non-flat Image) has executed evidence only on Linux
(Xvfb/XTEST, 2026-10-01) and macOS from a different runtime context (kit
0.1.41 CGEvent pass, 2026-10-03). This harness binds that leg to the current
distribution so a trusted-input context can execute it end to end.

Session flow (GUI mode on macOS):
  1. install/enable the served distribution zip (NM_ARCHIVE_ZIP) with saved
     preferences, isolated BLENDER_USER_RESOURCES.
  2. record host versions + the Blender-side accessibility trust probe
     (AXIsProcessTrusted via ctypes) — measured and recorded, never assumed.
  3. scripted setup: compositor editor area repurposed in place, empty Text
     datablock created, panel draw methods wrapped with counters (a panel's
     draw runs only when its tab is active), click-point layout map written
     to NM_GUI_DIR for the companion driver.
  4. a modal operator logs EVERY keyboard/mouse event the window receives.
     The interactive steps are gated on real events arriving (via driver
     markers + event log + draw counters + datablock contents):
       - tab: real clicks select the Noisemaker tab (draw-counter proof)
       - typing: keystrokes must land byte-for-byte in the Text datablock
       - bake: a real click on the Bake row must produce a non-flat Image
  5. verdicts written as JSON to NM_EVIDENCE_DIR:
       PASS           — all three steps passed with real events received
       NOT-DELIVERED  — the driver's window expired with steps unfinished
                        (no trusted driver; measured, recorded verbatim)
       FAIL           — a step's marker arrived but its check failed
     then the session quits itself.

Driver contract (companion driver lives in the job's trusted-input context,
not in this repository; it handshakes through NM_GUI_DIR):
  - reads NM_GUI_DIR/state.json (written by this harness) for the layout map
    and phase
  - performs the real input: tab-strip clicks, typing into the Text datablock
    (which it must select first), a click on the estimated Bake row
  - after each step writes a marker file: m_tab_done, m_typing_done,
    m_bake_done
  - must check AXIsProcessTrusted() in its own context and refuse to run
    untrusted: without trust, synthetic events cannot reach another
    application, so an untrusted run cannot deliver and this session will
    record NOT-DELIVERED with zero real events after its window expires.

Usage (GUI mode, windowed):
  BLENDER_USER_RESOURCES=<fresh dir> blender --factory-startup \
      --window-geometry 40 40 1200 800 \
      --python-expr "import bpy; bpy.context.preferences.view.show_splash = False" \
      --python blender/harness/test_interactive_mac.py
  NM_ARCHIVE_ZIP points at the distribution zip to install.
  NM_EVIDENCE_DIR receives the session JSON; NM_GUI_DIR receives the layout
  map (click points) and the driver's step markers.
"""
import json
import os
import sys
import time
import traceback

import bpy

EVIDENCE = os.environ.get("NM_EVIDENCE_DIR", "/tmp/nm-mac-interactive")
GUI_DIR = os.environ.get("NM_GUI_DIR", "/tmp/nm-mac-gui")
ARCHIVE = os.environ.get("NM_ARCHIVE_ZIP")

PROGRAM = (
    "search synth, filter\n"
    "\n"
    "noise(seed: 1, scaleX: 50, scaleY: 50).adjust().write(o0)\n"
    "render(o0)\n"
)

STEP_WINDOW = 15.0      # seconds the driver gets per step
TOTAL_WINDOW = 60.0     # hard session ceiling (driver absent → NOT-DELIVERED)

STATE = {
    "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "archive": ARCHIVE,
    "trust": None,
    "events": {"keys": [], "clicks": []},
    "draws": {},
    "steps": {"tab": None, "typing": None, "bake": None},
    "fails": [],
    "window": TOTAL_WINDOW,
}

_TAB_MARKER = os.path.join(GUI_DIR, "m_tab_done")
_TYPING_MARKER = os.path.join(GUI_DIR, "m_typing_done")
_BAKE_MARKER = os.path.join(GUI_DIR, "m_bake_done")


def save_state(verdict=None):
    STATE["end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if verdict:
        STATE["verdict"] = verdict
    os.makedirs(EVIDENCE, exist_ok=True)
    out = os.path.join(EVIDENCE, "session-mac.json")
    with open(out, "w") as f:
        json.dump(STATE, f, indent=1, default=repr)
    return out


def ax_trust():
    """Blender-side trust probe (measured; the driver re-checks itself)."""
    import ctypes
    try:
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except OSError:
        return None


def record_versions():
    import gpu
    import gpu.platform
    STATE["trust"] = ax_trust()
    STATE["blender"] = bpy.app.version_string
    STATE["gpu_vendor"] = gpu.platform.vendor_get()
    STATE["gpu_renderer"] = gpu.platform.renderer_get()
    STATE["gpu_backend"] = gpu.platform.backend_type_get()
    print("  host  OK   blender=%r gpu=%r %r %r" % (
        bpy.app.version_string, STATE["gpu_vendor"],
        STATE["gpu_renderer"], STATE["gpu_backend"]))
    print("  host  OK   AXIsProcessTrusted(blender ctx)=%r" % (STATE["trust"],))


def install():
    import addon_utils
    assert ARCHIVE, "NM_ARCHIVE_ZIP must point at the distribution zip"
    r = bpy.ops.preferences.addon_install(
        'EXEC_DEFAULT', filepath=ARCHIVE, overwrite=True)
    assert r == {'FINISHED'}, "addon_install returned %r" % (r,)
    mod = addon_utils.enable("noisemaker_blender", default_set=True)
    assert mod is not None, "addon_enable failed"
    assert addon_utils.check("noisemaker_blender")[1], "addon not enabled"
    bpy.ops.wm.save_userpref()
    STATE["steps"]["install"] = {"archive": ARCHIVE, "ok": True}
    print("  install OK  %s enabled" % ARCHIVE)


def wrap_panels():
    """Wrap the REGISTERED panel draw methods (the sibling harness pattern:
    wrapping the registered bpy.types classes after addon enable is what the
    real panel draw path calls; wrapping the pre-registration source classes
    would not affect the registered panels)."""
    counters = STATE["draws"]
    for cls_name in ("NOISEMAKER_PT_compositor", "NOISEMAKER_PT_image_editor"):
        cls = getattr(bpy.types, cls_name, None)
        assert cls is not None, "panel class not registered: %s" % cls_name
        counters[cls_name] = 0
        original = cls.draw

        def wrapped(self, context, _original=original, _name=cls_name):
            counters[_name] += 1
            return _original(self, context)
        cls.draw = wrapped
    print("  setup  OK   registered panel draw counters armed: %r" % (counters,))


def setup_layout():
    """Scripted layout: repurpose the compositor editor in place; the empty
    Text datablock is created from script (that creation is scripted in every
    harness; the *typing* into it is the real-input step). Also writes the
    click-point layout map the companion driver uses."""
    window = bpy.context.window
    area = window.screen.areas[0]
    area.type = 'NODE_EDITOR'
    for space in area.spaces:
        if space.type == 'NODE_EDITOR':
            space.node_tree = bpy.context.scene.compositing_node_group
            space.show_region_toolbar = True
            space.show_region_ui = True

    text = bpy.data.texts.new("NM_program")
    text.write("")
    st = bpy.context.scene.noisemaker
    st.source_mode = 'TEXT'
    st.text = text.name
    st.image_name = "NM_interactive"

    regions = {r.type: (r.x, r.y, r.width, r.height) for r in area.regions}
    ui_region = regions.get('UI')
    if ui_region:
        x, y, w, h = ui_region
        layout_map = {
            "area": "NODE_EDITOR",
            "ui_region": {"x": x, "y": y, "w": w, "h": h},
            "tab_strip": {
                "x": x + w - 10,
                "y_start": y + h - 30,
                "click_step": 24,
                "note": "click downward until the Noisemaker panel draws",
            },
            "bake_row": {
                "x": x + w // 2,
                "y": y + 250,
                "note": "estimated: source_mode/text rows (~2 rows) then "
                        "size/time/frames/timestep rows, then the Bake "
                        "button; recorded as an estimate",
            },
            "text_widget": {
                "x": x + w // 2,
                "y": y + h - 60,
                "note": "estimated: the Text datablock row under source_mode",
            },
        }
    else:
        layout_map = {"area": "NODE_EDITOR", "ui_region": None}
    os.makedirs(GUI_DIR, exist_ok=True)
    with open(os.path.join(GUI_DIR, "state.json"), "w") as f:
        json.dump({"phase": "awaiting-driver", "layout": layout_map,
                   "program": PROGRAM}, f, indent=1)
    STATE["layout"] = layout_map
    STATE["steps"]["install"]["layout_map"] = "NM_GUI_DIR/state.json"
    print("  setup  OK   compositor area armed, text datablock created, "
          "layout map written to NM_GUI_DIR")
    return area


def image_is_flat(img):
    """Float32 readback (the sibling harness pattern: a byte-format buffer can
    be rejected for float Image pixel buffers)."""
    import numpy as np
    w, h = img.size[0], img.size[1]
    if w == 0 or h == 0:
        return True
    buf = bytearray(w * h * 4)
    img.pixels.foreach_get(buf)
    buf = np.frombuffer(buf, dtype=np.float32)
    px = buf.reshape(-1, 4)
    return float(px[:, :3].std()) <= 0.01


class EventLog(bpy.types.Operator):
    bl_idname = "nm.interactive_log"
    bl_label = "Interactive event log"

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        self.t0 = time.time()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.value == 'PRESS':
            if event.type in {"LEFTMOUSE", "RIGHTMOUSE"}:
                STATE["events"]["clicks"].append(
                    {"t": round(time.time() - self.t0, 3),
                     "type": event.type,
                     "x": event.mouse_x, "y": event.mouse_y})
            else:
                STATE["events"]["keys"].append(
                    {"t": round(time.time() - self.t0, 3),
                     "type": event.type, "value": event.value,
                     "unicode": event.unicode})
        if time.time() - self.t0 > TOTAL_WINDOW:
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


def judge_tab():
    drawn = STATE["draws"]["NOISEMAKER_PT_compositor"] > 0
    return {"marker": True, "panel_drawn": drawn,
            "ok": drawn, "note": "draw-counter proof" if drawn
            else "no Noisemaker panel draw after tab-step marker"}


def judge_typing():
    text = bpy.data.texts.get("NM_program")
    got = text.as_string() if text else None
    return {"marker": True, "expected_bytes": len(PROGRAM),
            "got_bytes": len(got) if got is not None else None,
            "match": got == PROGRAM, "ok": got == PROGRAM}


def judge_bake():
    """Judge the declared bake output only: the named Image datablock
    scene.noisemaker.image_name ("NM_interactive"), not any non-flat image."""
    st = bpy.context.scene.noisemaker
    name = st.image_name
    img = bpy.data.images.get(name)
    detail = {"expected_name": name, "found": img is not None}
    if img is not None:
        try:
            detail["size"] = list(img.size)
            detail["flat"] = image_is_flat(img)
        except Exception:
            detail["flat"] = None
    ok = img is not None and detail.get("flat") is False
    return {"marker": True, "image": detail, "ok": ok,
            "note": "declared bake output is non-flat" if ok
                    else "the named bake output image is missing or flat"}


JUDGES = {"tab": judge_tab, "typing": judge_typing, "bake": judge_bake}
MARKERS = {"tab": _TAB_MARKER, "typing": _TYPING_MARKER, "bake": _BAKE_MARKER}


def tick_driver_watch():
    """Timer: poll driver markers, judge each step as it lands, compute the
    final verdict, and quit the session (timeout → NOT-DELIVERED, recorded
    verbatim)."""
    try:
        for step, marker in MARKERS.items():
            if STATE["steps"][step] is None and os.path.exists(marker):
                os.remove(marker)
                STATE["steps"][step] = JUDGES[step]()
                STATE["last_marker_t"] = time.time() - STATE["t0"]
                STATE["last_marker_step"] = step

        elapsed = time.time() - STATE["t0"]
        done = all(STATE["steps"][s] is not None
                   for s in ("tab", "typing", "bake"))
        landed = [s for s in ("tab", "typing", "bake")
                  if STATE["steps"][s] is not None]
        # Per-step window: measured from the most recent marker landing (a
        # fixed point recorded when the marker is consumed), so a stalled
        # driver after a landed step ends the session instead of waiting for
        # TOTAL_WINDOW.
        timeout = elapsed > TOTAL_WINDOW or (
            landed and elapsed > STATE["last_marker_t"] + STEP_WINDOW
            and not done)

        if done or timeout:
            real_events = bool(STATE["events"]["keys"]
                               or STATE["events"]["clicks"])
            results = {s: (STATE["steps"][s] if STATE["steps"][s] is not None
                           else {"marker": False, "ok": False,
                                 "note": "driver window expired before this "
                                         "step's marker; no real input "
                                         "delivered to this session"})
                       for s in ("tab", "typing", "bake")}
            if all(r["ok"] for r in results.values()) and real_events:
                verdict = "PASS"
            elif not real_events:
                verdict = "NOT-DELIVERED"
            else:
                verdict = "FAIL"
            STATE["verdict"] = verdict
            STATE["steps"] = results
            STATE["elapsed"] = round(elapsed, 3)
            out = save_state(verdict)
            print("  SESSION-MAC %s  (%s)" % (verdict, out))
            for s in ("tab", "typing", "bake"):
                print("    %s: %s" % (s, results[s]))
            sys.stdout.flush()
            bpy.app.timers.unregister(tick_driver_watch)
            os._exit(0)
        if landed:
            STATE["elapsed_now"] = elapsed
    except Exception:
        STATE["fails"].append(traceback.format_exc())
        out = save_state("FAIL")
        print("  SESSION-MAC FAIL (exception) %s" % out)
        traceback.print_exc()
        sys.stdout.flush()
        bpy.app.timers.unregister(tick_driver_watch)
        os._exit(1)
    return 0.5


def main():
    record_versions()
    install()
    wrap_panels()
    setup_layout()
    try:
        bpy.utils.register_class(EventLog)
        r = bpy.ops.nm.interactive_log('INVOKE_DEFAULT')
        print("  event logger armed: %s" % (r,))
    except Exception:
        STATE["fails"].append(traceback.format_exc())
    STATE["t0"] = time.time()
    save_state()
    bpy.app.timers.register(tick_driver_watch, first_interval=0.5)
    print("  awaiting real input from companion driver "
          "(markers in NM_GUI_DIR; window %.0fs)" % TOTAL_WINDOW)


if bpy.app.background:
    print("INTERACTIVE-MAC SKIP: these checks need GUI mode; run without -b")
else:
    try:
        main()
    except Exception:
        STATE["fails"].append(traceback.format_exc())
        traceback.print_exc()
        save_state("FAIL")
        sys.stdout.flush()
        os._exit(1)
