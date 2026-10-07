"""Sidebar panels that drive a scene-wide bake (the no-node workflow).

Shown in the Compositor and the Image Editor under a "Noisemaker" tab — the two places a
user wires up / inspects the baked Image. They read and write ``scene.noisemaker`` and
invoke ``noisemaker.bake`` with no operator overrides (so it uses those scene settings).
"""
import bpy


def _draw(layout, st):
    layout.prop(st, "source_mode", text="")
    if st.source_mode == 'TEXT':
        layout.prop(st, "text", text="")
    else:
        layout.prop(st, "filepath", text="")
    col = layout.column(align=True)
    col.prop(st, "size")
    col.prop(st, "time")
    col.prop(st, "frames")
    col.prop(st, "timestep")
    layout.prop(st, "image_name", text="Image")
    layout.operator("noisemaker.bake", text="Bake", icon='RENDER_STILL')


class _NoisemakerPanel:
    bl_region_type = 'UI'
    bl_category = "Noisemaker"
    bl_label = "Bake"

    def draw(self, context):
        st = getattr(context.scene, "noisemaker", None)
        if st is None:
            self.layout.label(text="Noisemaker not registered")
            return
        _draw(self.layout, st)


class NOISEMAKER_PT_compositor(_NoisemakerPanel, bpy.types.Panel):
    bl_idname = "NOISEMAKER_PT_compositor"
    bl_space_type = 'NODE_EDITOR'

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return getattr(sd, "tree_type", "") == 'CompositorNodeTree'


class NOISEMAKER_PT_image_editor(_NoisemakerPanel, bpy.types.Panel):
    bl_idname = "NOISEMAKER_PT_image_editor"
    bl_space_type = 'IMAGE_EDITOR'




def _draw_live(layout, context):
    from ..integration.lifecycle import registry
    from ..integration.parameters import BlenderPropertyAdapter
    scene = context.scene
    row = layout.row()
    row.template_list("UI_UL_list", "noisemaker_live", scene, "noisemaker_instances",
                      scene, "noisemaker_active_index", rows=3)
    buttons = row.column(align=True)
    buttons.operator("noisemaker.live_add", text="", icon='ADD')
    buttons.operator("noisemaker.live_remove", text="", icon='REMOVE')
    index = scene.noisemaker_active_index
    if index < 0 or index >= len(scene.noisemaker_instances):
        return
    config = scene.noisemaker_instances[index]
    layout.prop(config, "name")
    layout.prop(config, "source_mode", text="")
    if config.source_mode == 'TEXT':
        layout.prop(config, "text")
    elif config.source_mode == 'FILE':
        layout.prop(config, "filepath")
    else:
        layout.prop(config, "source")
    row = layout.row(align=True)
    row.operator("noisemaker.live_toggle", text=("Live" if not config.live_enabled else
                                                  "Resume" if config.paused else "Pause"),
                 icon='PLAY' if config.paused or not config.live_enabled else 'PAUSE')
    row.operator("noisemaker.live_reset", text="Reset", icon='FILE_REFRESH')
    layout.prop(config, "time_mode")
    layout.label(text="Preview" if config.time_mode == 'free_run' else "Scene timeline")
    layout.label(text="Final frames: use scripted rendering", icon='INFO')
    layout.label(text="F12 / native animation do not refresh live output")
    row = layout.row(align=True)
    row.prop(config, "preview_width")
    row.prop(config, "preview_height")
    layout.prop(config, "preview_fps")
    row = layout.row(align=True)
    row.prop(config, "render_width")
    row.prop(config, "render_height")
    layout.prop(config, "origin_frame")
    layout.prop(config, "loop_seconds")
    layout.prop(config, "offset_seconds")
    layout.prop(config, "fixed_step_seconds")
    layout.prop(config, "color_role")
    layout.prop(config, "alpha_mode")
    layout.prop(config, "output_image")
    layout.prop(config, "pack_output")
    if config.input_bindings:
        inputs_box = layout.box()
        inputs_box.label(text="Host Images")
        for item in config.input_bindings:
            row = inputs_box.row(align=True)
            row.prop(item, "binding_name", text="")
            row.prop(item, "image", text="")
    if config.last_error:
        layout.label(text=config.last_error[:120], icon='ERROR')
    record = registry.get(scene, config.instance_id)
    progress = registry.scheduler.status(registry._key(scene, config.instance_id)).replay_progress
    if progress is not None:
        layout.label(text="Replay %d / %d" % (progress.completed_steps, progress.target_step),
                     icon='TIME')
    if record.bindings is not None:
        box = layout.box()
        box.label(text="Parameters")
        adapter = BlenderPropertyAdapter(config)
        for key in record.bindings.active_keys:
            binding = record.bindings.binding(key)
            prop = adapter.property_name(key)
            label = key.rsplit('.', 1)[-1]
            if binding.spec.choices:
                label += " (" + adapter.enum_label(record.bindings, key) + ")"
            if prop in config:
                box.prop(config, '["%s"]' % prop, text=label)
        if record.bindings.orphan_keys:
            orphan_box = layout.box()
            orphan_box.label(text="Orphaned bindings", icon='INFO')
            for key in record.bindings.orphan_keys:
                orphan_box.label(text=key)


class NOISEMAKER_PT_live_compositor(bpy.types.Panel):
    bl_idname = "NOISEMAKER_PT_live_compositor"
    bl_label = "Live"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Noisemaker"
    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == 'CompositorNodeTree'
    def draw(self, context):
        _draw_live(self.layout, context)


class NOISEMAKER_PT_live_image_editor(bpy.types.Panel):
    bl_idname = "NOISEMAKER_PT_live_image_editor"
    bl_label = "Live"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Noisemaker"
    def draw(self, context):
        _draw_live(self.layout, context)


_CLASSES = (NOISEMAKER_PT_compositor, NOISEMAKER_PT_image_editor,
            NOISEMAKER_PT_live_compositor, NOISEMAKER_PT_live_image_editor)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
