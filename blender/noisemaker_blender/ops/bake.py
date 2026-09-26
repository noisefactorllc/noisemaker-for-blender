"""NOISEMAKER_OT_bake — the integration seam.

DSL source  ->  compile_graph (in-addon Python compiler, no external reference)
            ->  GpuBackend render (gpu module)
            ->  Image datablock  (the compositor consumes it via a stock Image node)

The operator is self-contained and scriptable: every input is an operator property, so a
script or a node can drive it directly, e.g.

    bpy.ops.noisemaker.bake(dsl="noise().write(o0)\\nrender(o0)", image_name="X", size=256)

When a property is left at its sentinel default the operator falls back to the scene
settings (``context.scene.noisemaker``), which is what the N-panels populate.

Long bakes and cancellation: invoked from a window (button click) with more than one
frame, the operator runs MODAL — one frame per timer tick, so the UI stays responsive
between frames and pressing ESC cancels between frames (the single frame already being
rendered always completes; nothing is written to the Image until every frame finished,
so a cancelled bake leaves the target Image exactly as it was). Called from a script
(EXEC_DEFAULT) or in a headless session it runs synchronously to completion like any
operator execute().

Image ownership: the bake only reuses an existing Image datablock that a previous bake
created (marked ``noisemaker_baked``). Any other Image that happens to carry the target
name is never resized or overwritten — the bake writes to a fresh unique name instead
and reports it, so user content cannot be destroyed by a name collision.
"""
import os

import bpy

# Pure-Python imports are safe at module top (the gates never import this module, but the
# heavy gpu-dependent backend is imported lazily in execute() to keep import side-effect free).
from ..compiler import compile_graph, CompilationError, ExpansionError
from ..runtime import graph_loader, pipeline

# .../noisemaker_blender/ops/bake.py -> .../noisemaker_blender/shaders/effects
_ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SHADERS_ROOT = os.path.join(_ADDON, "shaders", "effects")

# Custom property stamped on every Image this operator creates/rebakes. Only marked
# images are reused by name; anything else is user content and gets a fresh name.
_OWNERSHIP_MARKER = "noisemaker_baked"


def _read_source(op, scene_settings):
    """Resolve DSL text from (in priority) explicit op.dsl, a named/scene Text datablock,
    or a file path. Returns (source_str, None) or (None, error_message)."""
    if op.dsl:
        return op.dsl, None

    st = scene_settings
    # Text datablock: explicit op.text_name wins, else the scene pointer.
    text_db = None
    if op.text_name:
        text_db = bpy.data.texts.get(op.text_name)
        if text_db is None:
            return None, "Text block %r not found" % op.text_name
    elif st and st.source_mode == 'TEXT' and st.text:
        text_db = st.text
    if text_db is not None:
        return text_db.as_string(), None

    # File path: explicit op.filepath, else scene filepath (when in FILE mode).
    path = op.filepath or (st.filepath if (st and st.source_mode == 'FILE') else "")
    if path:
        path = bpy.path.abspath(path)
        if not os.path.exists(path):
            return None, "DSL file not found: %s" % path
        with open(path) as fh:
            return fh.read(), None

    return None, "No DSL source set (pick a Text block or a .dsl file)"


def _write_image(name, arr):
    """Write a top-down uint8 HxWx4 array into a float Image datablock (created if needed),
    bottom-up and Non-Color so the stored values are the exact rendered values.

    Only an Image this operator previously baked (ownership marker) is reused; any other
    Image with the target name is left untouched and a fresh unique name is used, so a
    name collision can never resize or overwrite user content.
    """
    import numpy as np
    h, w = arr.shape[:2]
    img = bpy.data.images.get(name)
    if img is not None and not img.get(_OWNERSHIP_MARKER):
        # Not ours: never touch it. Bake under the next free unique name instead.
        candidate = name
        i = 1
        while bpy.data.images.get(candidate) is not None:
            candidate = "%s.%03d" % (name, i)
            i += 1
        img = None
        name = candidate
    if img is None:
        img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
    elif tuple(img.size) != (w, h):
        img.scale(w, h)
    # Don't let an unused datablock get purged between bakes.
    img.use_fake_user = True
    img[_OWNERSHIP_MARKER] = True
    # Raw values, no view transform — matches the linear golden capture. MUST be set
    # BEFORE writing pixels: changing colorspace on a generated image regenerates (and
    # clobbers) the pixel buffer, which would leave the bake black.
    try:
        img.colorspace_settings.name = 'Non-Color'
    except Exception:
        pass
    # GPU/golden order is top-down; Image datablocks are bottom-up -> flip back.
    flat = np.ascontiguousarray(arr[::-1], dtype=np.float32).reshape(-1) / 255.0
    img.pixels.foreach_set(flat)
    img.update()
    return img


class _BakeJob:
    """Resolved bake inputs + the frame stepper (shared by the sync and modal paths)."""

    def __init__(self, op, context):
        self.error = None
        st = getattr(context.scene, "noisemaker", None)
        self.settings = st

        src, err = _read_source(op, st)
        if err:
            self.error = err
            return

        # Resolve params: explicit op value (non-sentinel) wins, else scene, else default.
        self.size = op.size if op.size > 0 else (st.size if st else 256)
        self.time = op.time if op.time >= 0.0 else (st.time if st else 0.25)
        self.frames = op.frames if op.frames > 0 else (st.frames if st else 1)
        self.timestep = op.timestep if op.timestep >= 0.0 else (st.timestep if st else 0.0)
        self.requested_name = op.image_name or (st.image_name if st else "") or "Noisemaker"

        try:
            graph = graph_loader.Graph(compile_graph(src))
        except (CompilationError, ExpansionError) as e:
            self.error = "DSL compile failed: %s" % e
            return
        except Exception as e:                                       # lex/parse/validate errors
            self.error = "DSL error: %s" % e
            return

        # Render via the gpu backend (imported lazily — needs a live GPU context).
        try:
            from ..backend.gpu_backend import GpuBackend
            self.backend = GpuBackend(_SHADERS_ROOT, self.size)
            self.stepper = pipeline.FrameStepper(
                self.backend, graph, time=self.time, frames=self.frames,
                timestep=self.timestep)
        except Exception as e:
            self.error = "Render failed: %s" % e

    def finish(self, op):
        """Write the final image (if the job rendered) and release the backend."""
        try:
            if self.error is None:
                arr = self.stepper.result()
                img = _write_image(self.requested_name, arr)
                if img.name != self.requested_name:
                    op.report({'WARNING'},
                              "Image '%s' exists and was not created by Noisemaker — "
                              "baked to '%s' instead (the existing image is untouched)"
                              % (self.requested_name, img.name))
                op.report({'INFO'}, "Baked '%s' (%dx%d, %d frame%s)"
                          % (img.name, img.size[0], img.size[1], self.frames,
                             "" if self.frames == 1 else "s"))
        finally:
            backend = getattr(self, "backend", None)
            if backend is not None:
                backend.free()
                self.backend = None


class NOISEMAKER_OT_bake(bpy.types.Operator):
    """Compile the Noisemaker DSL and bake it into an Image datablock.

    Long bakes (more than one frame) run modally when invoked from a window: the UI stays
    responsive, progress is shown in the status bar, and ESC cancels between frames.
    """
    bl_idname = "noisemaker.bake"
    bl_label = "Bake Noisemaker"
    bl_options = {'REGISTER'}

    # All inputs are operator properties (scriptable). SKIP_SAVE + sentinel defaults mean
    # "unset -> fall back to scene settings".
    dsl: bpy.props.StringProperty(name="DSL", default="", options={'SKIP_SAVE'})
    text_name: bpy.props.StringProperty(name="Text Block", default="", options={'SKIP_SAVE'})
    filepath: bpy.props.StringProperty(name="DSL File", default="", subtype='FILE_PATH',
                                       options={'SKIP_SAVE'})
    image_name: bpy.props.StringProperty(name="Image", default="", options={'SKIP_SAVE'})
    size: bpy.props.IntProperty(name="Size", default=0, options={'SKIP_SAVE'})
    time: bpy.props.FloatProperty(name="Time", default=-1.0, options={'SKIP_SAVE'})
    frames: bpy.props.IntProperty(name="Frames", default=0, options={'SKIP_SAVE'})
    timestep: bpy.props.FloatProperty(name="Timestep", default=-1.0, options={'SKIP_SAVE'})

    # --- internal state (not user-facing) --------------------------------------------
    _job = None
    _timer = None

    def _modal_active(self, job, context):
        """True when the long-bake modal path should be used for this invocation.

        Decides on the RESOLVED frame count (op value or scene settings — the sidebar
        panels invoke with no overrides), so a scene-configured long bake is modal too.
        """
        return job.frames > 1 and context.window is not None

    def execute(self, context):
        job = _BakeJob(self, context)
        if job.error:
            self.report({'ERROR'}, job.error)
            return {'CANCELLED'}
        try:
            while job.stepper.step():
                pass
            self._job = job
            job.finish(self)
        except Exception as e:
            job.error = "Render failed: %s" % e
            job.finish(self)
            self.report({'ERROR'}, job.error)
            return {'CANCELLED'}
        finally:
            self._job = None
        return {'FINISHED'}

    def invoke(self, context, event):
        job = _BakeJob(self, context)
        if job.error:
            self.report({'ERROR'}, job.error)
            return {'CANCELLED'}
        self._job = job
        if not self._modal_active(job, context):
            # Short bake (or no window: scripts/headless): run synchronously.
            try:
                while job.stepper.step():
                    pass
                job.finish(self)
            except Exception as e:
                job.error = "Render failed: %s" % e
                job.finish(self)
                self.report({'ERROR'}, job.error)
                return {'CANCELLED'}
            self._job = None
            return {'FINISHED'}
        # Long bake: hand control back to the event loop, one frame per timer tick.
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        self._progress(context, 0)
        return {'RUNNING_MODAL'}

    def _progress(self, context, done):
        context.workspace.status_text_set(
            "Baking Noisemaker: frame %d/%d — ESC to cancel" % (done, self._job.frames))

    def modal(self, context, event):
        job = self._job
        if event.type == 'ESC':
            self._release(job, context)
            self.report({'WARNING'}, "Bake cancelled after %d of %d frames — "
                                     "the Image was not modified"
                        % (job.stepper.frame + 1, job.frames))
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        try:
            more = job.stepper.step()
        except Exception as e:
            job.error = "Render failed: %s" % e
            self._release(job, context)
            self.report({'ERROR'}, job.error)
            return {'CANCELLED'}
        if more:
            self._progress(context, job.stepper.frame + 1)
            return {'RUNNING_MODAL'}
        try:
            job.finish(self)
        except Exception as e:
            job.error = "Image write failed: %s" % e
            self._release(job, context)
            self.report({'ERROR'}, job.error)
            return {'CANCELLED'}
        self._cleanup(context)
        return {'FINISHED'}

    def _release(self, job, context):
        """Free the backend without writing anything and clear the modal timer/status
        text (cancel / mid-render failure / final-image-write failure)."""
        self._job = None
        if job is not None:
            job.error = job.error or "cancelled"
            job.finish(self)              # error set -> only frees the backend
        self._cleanup(context)

    def _cleanup(self, context):
        self._job = None
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        context.workspace.status_text_set(None)


def register():
    bpy.utils.register_class(NOISEMAKER_OT_bake)


def unregister():
    bpy.utils.unregister_class(NOISEMAKER_OT_bake)
