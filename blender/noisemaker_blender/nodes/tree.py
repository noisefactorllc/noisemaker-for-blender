"""The bespoke Noisemaker node editor (docs/BLENDER-PLATFORM-NOTES.md §1).

The stock compositor is closed to Python nodes, so this is a separate CUSTOM ``NodeTree``
that provides the graph UI. A ``NoisemakerProgramNode`` holds a DSL program + its bake
params; its Bake button drives ``noisemaker.bake`` scoped to the node, producing an Image
the real compositor consumes through a stock Image node.

This is intentionally a thin authoring surface — the DSL itself is the graph language
(``noise().adjust().write(o0)``); the node is where you keep one program and bake it.
"""
import bpy
from bpy.types import NodeTree, Node

from .. import props


class NoisemakerNodeTree(NodeTree):
    bl_idname = "NoisemakerNodeTree"
    bl_label = "Noisemaker"
    bl_icon = 'NODETREE'


class NoisemakerProgramNode(Node):
    """A Noisemaker DSL program that bakes to an Image datablock"""
    bl_idname = "NoisemakerProgramNode"
    bl_label = "Noisemaker Program"
    bl_icon = 'IMAGE_DATA'

    # Per-node copy of the bake settings (reuses the shared property factories so the node
    # and the scene panel expose identical controls).
    source_mode: bpy.props.EnumProperty(name="Source", items=props.SOURCE_ITEMS, default='TEXT')
    text: bpy.props.PointerProperty(name="DSL Text", type=bpy.types.Text)
    filepath: bpy.props.StringProperty(name="DSL File", subtype='FILE_PATH')
    size: props._size()
    time: props._time()
    frames: props._frames()
    timestep: props._timestep()
    image_name: props._image_name()
    live_instance_id: bpy.props.StringProperty(name="Live Instance ID", default="")

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == NoisemakerNodeTree.bl_idname

    def init(self, context):
        # A cosmetic output socket so the node reads as a producer in the editor.
        self.outputs.new('NodeSocketColor', "Image")
        self.width = 240

    def draw_buttons(self, context, layout):
        layout.prop(self, "source_mode", text="")
        if self.source_mode == 'TEXT':
            layout.prop(self, "text", text="")
        else:
            layout.prop(self, "filepath", text="")
        col = layout.column(align=True)
        col.prop(self, "size")
        col.prop(self, "time")
        col.prop(self, "frames")
        col.prop(self, "timestep")
        layout.prop(self, "image_name", text="Image")

        op = layout.operator("noisemaker.bake", text="Bake", icon='RENDER_STILL')
        # Drive the operator entirely from this node's fields (decoupled from the scene group).
        op.text_name = self.text.name if (self.source_mode == 'TEXT' and self.text) else ""
        op.filepath = self.filepath if self.source_mode == 'FILE' else ""
        op.size = self.size
        op.time = self.time
        op.frames = self.frames
        op.timestep = self.timestep
        op.image_name = self.image_name
        scene = context.scene
        live = next((item for item in scene.noisemaker_instances
                     if item.instance_id == self.live_instance_id), None) if scene else None
        if live is None:
            start = layout.operator("noisemaker.live_add", text="Start Live", icon='PLAY')
            start.source_mode = self.source_mode
            start.text_name = self.text.name if self.text else ""
            start.filepath = self.filepath
            start.preview_width = self.size
            start.preview_height = self.size
            start.image_name = self.image_name
            start.node_tree_name = self.id_data.name
            start.node_name = self.name
        else:
            row = layout.row(align=True)
            toggle = row.operator("noisemaker.live_toggle",
                                  text="Resume" if live.paused else "Pause", icon='PLAY' if live.paused else 'PAUSE')
            toggle.instance_id = live.instance_id
            reset = row.operator("noisemaker.live_reset", text="Reset", icon='FILE_REFRESH')
            reset.instance_id = live.instance_id
            try:
                output_image = live.output_image
            except ValueError as exc:
                layout.label(text=str(exc)[:90], icon='ERROR')
            else:
                layout.label(text="Live Image: " + (output_image.name if output_image else "None"),
                             icon='IMAGE_DATA')
            if live.last_error:
                layout.label(text=live.last_error[:90], icon='ERROR')


def _add_menu(self, context):
    """Add 'Noisemaker Program' to Shift+A, but only inside a Noisemaker node tree."""
    space = context.space_data
    if getattr(space, "tree_type", "") == NoisemakerNodeTree.bl_idname:
        self.layout.operator("node.add_node", text="Program",
                             icon='IMAGE_DATA').type = NoisemakerProgramNode.bl_idname


_CLASSES = (NoisemakerNodeTree, NoisemakerProgramNode)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.NODE_MT_add.append(_add_menu)


def unregister():
    bpy.types.NODE_MT_add.remove(_add_menu)
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
