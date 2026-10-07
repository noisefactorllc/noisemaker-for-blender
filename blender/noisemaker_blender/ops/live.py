"""Live instance controls; GPU work remains in the qualified GUI timer."""
import bpy

from ..integration.lifecycle import registry
from ..integration.persistence import create_instance


def _selected(scene):
    items = scene.noisemaker_instances
    index = scene.noisemaker_active_index
    return items[index] if 0 <= index < len(items) else None


class NOISEMAKER_OT_live_add(bpy.types.Operator):
    bl_idname = "noisemaker.live_add"
    bl_label = "Add Live Program"
    bl_options = {'REGISTER', 'UNDO'}
    source_mode: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    source: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    text_name: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    filepath: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    preview_width: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    preview_height: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    image_name: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    node_tree_name: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    node_name: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        bake = scene.noisemaker
        instance = create_instance(scene, self.source, "Noisemaker")
        instance.source_mode = self.source_mode or bake.source_mode
        instance.text = bpy.data.texts.get(self.text_name) if self.text_name else bake.text
        instance.filepath = self.filepath or bake.filepath
        instance.preview_width = self.preview_width or bake.size
        instance.preview_height = self.preview_height or bake.size
        instance.image_name = self.image_name or bake.image_name
        instance.live_enabled = True
        scene.noisemaker_active_index = len(scene.noisemaker_instances) - 1
        if self.node_tree_name and self.node_name:
            tree = bpy.data.node_groups.get(self.node_tree_name)
            node = tree.nodes.get(self.node_name) if tree is not None else None
            if node is not None and hasattr(node, "live_instance_id"):
                node.live_instance_id = instance.instance_id
        registry.get(scene, instance.instance_id)
        registry.mark_dirty(scene, instance.instance_id, "source")
        return {'FINISHED'}


class NOISEMAKER_OT_live_toggle(bpy.types.Operator):
    bl_idname = "noisemaker.live_toggle"
    bl_label = "Live / Pause"
    bl_options = {'REGISTER'}
    instance_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        instance = next((item for item in context.scene.noisemaker_instances
                         if item.instance_id == self.instance_id), None) if self.instance_id else _selected(context.scene)
        if instance is None:
            return {'CANCELLED'}
        if not instance.live_enabled:
            instance.live_enabled = True
            instance.paused = False
        else:
            instance.paused = not instance.paused
        registry.mark_dirty(context.scene, instance.instance_id, "configuration")
        return {'FINISHED'}


class NOISEMAKER_OT_live_reset(bpy.types.Operator):
    bl_idname = "noisemaker.live_reset"
    bl_label = "Reset Simulation"
    bl_options = {'REGISTER'}
    instance_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        instance = next((item for item in context.scene.noisemaker_instances
                         if item.instance_id == self.instance_id), None) if self.instance_id else _selected(context.scene)
        if instance is None:
            return {'CANCELLED'}
        registry.request_reset(context.scene, instance.instance_id)
        return {'FINISHED'}


class NOISEMAKER_OT_live_remove(bpy.types.Operator):
    bl_idname = "noisemaker.live_remove"
    bl_label = "Remove Live Program"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        index = scene.noisemaker_active_index
        instance = _selected(scene)
        if instance is None:
            return {'CANCELLED'}
        registry.remove(scene, instance.instance_id)
        scene.noisemaker_instances.remove(index)
        scene.noisemaker_active_index = min(index, len(scene.noisemaker_instances) - 1)
        return {'FINISHED'}


_CLASSES = (NOISEMAKER_OT_live_add, NOISEMAKER_OT_live_toggle,
            NOISEMAKER_OT_live_reset, NOISEMAKER_OT_live_remove)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
