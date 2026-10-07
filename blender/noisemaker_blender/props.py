"""Scene-level bake settings shared by the N-panels and the bake operator.

Exposed at ``context.scene.noisemaker``. The CUSTOM node (nodes/tree.py) keeps its own
copy of these on the node datablock so each node bakes independently; the panels drive
this scene-wide group for the no-node workflow.
"""
import bpy


# Used by both the scene group and the node so the two stay in lockstep.
def _size(default=256):
    return bpy.props.IntProperty(
        name="Size", default=default, min=8, max=4096, subtype='PIXEL',
        description="Square render resolution (the backend renders square)")


def _time(default=0.25):
    return bpy.props.FloatProperty(
        name="Time", default=default, min=0.0, max=1.0,
        description="Normalized animation time fed to the graph")


def _frames(default=1):
    return bpy.props.IntProperty(
        name="Frames", default=default, min=1, max=20000,
        description="Settle frames. 1 for single-pass effects; stateful sims "
                    "(navierStokes, agents, CAs) need many more")


def _timestep(default=0.0):
    return bpy.props.FloatProperty(
        name="Timestep", default=default, min=0.0, precision=5,
        description="0 = fixed-time deterministic render; >0 evolves continuous "
                    "solvers / agent sims to steady state (e.g. 0.00167 ~ 1/600)")


def _image_name(default="Noisemaker"):
    return bpy.props.StringProperty(
        name="Image", default=default,
        description="Target Image datablock (created if missing). Feed it into the "
                    "compositor via a stock Image node")


SOURCE_ITEMS = [
    ('TEXT', "Text Block", "DSL from a Blender Text datablock (edit it in the Text Editor)"),
    ('FILE', "File", "DSL from an external .dsl file on disk"),
]


class NoisemakerSettings(bpy.types.PropertyGroup):
    source_mode: bpy.props.EnumProperty(name="Source", items=SOURCE_ITEMS, default='TEXT')
    text: bpy.props.PointerProperty(name="DSL Text", type=bpy.types.Text)
    filepath: bpy.props.StringProperty(name="DSL File", subtype='FILE_PATH')
    size: _size()
    time: _time()
    frames: _frames()
    timestep: _timestep()
    image_name: _image_name()



LIVE_SOURCE_ITEMS = [
    ('INLINE', "Inline", "DSL stored with this instance"),
    *SOURCE_ITEMS,
]
TIME_MODE_ITEMS = [
    ('timeline', "Timeline", "Use evaluated scene frame and subframe"),
    ('free_run', "Free Run", "Preview advances while timeline is stopped"),
]


def _live_update(self, context):
    # Property callbacks mark work only. GPU evaluation belongs to the qualified
    # GUI timer; frame/dependency/render handlers must never render directly.
    try:
        from .integration.lifecycle import registry
        registry.mark_dirty(context.scene, self.instance_id, "configuration")
    except (AttributeError, KeyError):
        pass


class NoisemakerImageInput(bpy.types.PropertyGroup):
    binding_name: bpy.props.StringProperty(name="Binding", update=_live_update)
    image: bpy.props.PointerProperty(name="Image", type=bpy.types.Image, update=_live_update)


class NoisemakerLiveInstance(bpy.types.PropertyGroup):
    instance_id: bpy.props.StringProperty(name="Instance ID")
    name: bpy.props.StringProperty(name="Name", default="Noisemaker")
    source_mode: bpy.props.EnumProperty(name="Source", items=LIVE_SOURCE_ITEMS,
                                         default='INLINE', update=_live_update)
    source: bpy.props.StringProperty(name="DSL", update=_live_update)
    text: bpy.props.PointerProperty(name="DSL Text", type=bpy.types.Text, update=_live_update)
    filepath: bpy.props.StringProperty(name="DSL File", subtype='FILE_PATH', update=_live_update)
    preview_width: bpy.props.IntProperty(name="Preview Width", default=512, min=8, max=8192,
                                          subtype='PIXEL', update=_live_update)
    preview_height: bpy.props.IntProperty(name="Preview Height", default=512, min=8, max=8192,
                                           subtype='PIXEL', update=_live_update)
    preview_fps: bpy.props.IntProperty(name="Max Preview FPS", default=60, min=1, max=120,
                                        description="Maximum free-run preview updates per second",
                                        update=_live_update)
    render_width: bpy.props.IntProperty(name="Render Width", default=0, min=0, max=16384,
                                         subtype='PIXEL', description="0 uses scene render width")
    render_height: bpy.props.IntProperty(name="Render Height", default=0, min=0, max=16384,
                                          subtype='PIXEL', description="0 uses scene render height")
    origin_frame: bpy.props.IntProperty(name="Origin Frame", default=1, update=_live_update)
    loop_seconds: bpy.props.FloatProperty(name="Loop Seconds", default=10.0, min=0.001,
                                           update=_live_update)
    offset_seconds: bpy.props.FloatProperty(name="Time Offset", default=0.0,
                                             update=_live_update)
    fixed_step_seconds: bpy.props.FloatProperty(name="Simulation Step", default=0.0,
                                                 min=0.0, precision=6,
                                                 description="0 uses one step per scene frame",
                                                 update=_live_update)
    time_mode: bpy.props.EnumProperty(name="Preview Time", items=TIME_MODE_ITEMS,
                                       default='timeline', update=_live_update)
    live_enabled: bpy.props.BoolProperty(name="Live", default=False, update=_live_update)
    paused: bpy.props.BoolProperty(name="Pause", default=False, update=_live_update)
    image_name: bpy.props.StringProperty(name="Image Name", default="Noisemaker")
    color_role: bpy.props.EnumProperty(name="Output Role", items=[
        ('color', "Color", "Scene-linear color output"),
        ('data', "Data", "Numeric image data"),
        ('normal', "Normal", "Normal or vector image data"),
    ], default='color')
    alpha_mode: bpy.props.EnumProperty(name="Alpha", items=[
        ('PREMUL', "Premultiplied", "Noisemaker shader output convention"),
        ('STRAIGHT', "Straight", "Use only for a source with straight alpha"),
    ], default='PREMUL')
    output_image: bpy.props.PointerProperty(name="Output Image", type=bpy.types.Image)
    input_bindings: bpy.props.CollectionProperty(type=NoisemakerImageInput)
    pack_output: bpy.props.BoolProperty(name="Pack Output on Save", default=False,
                                        description="Store the current float Image pixels in the .blend file")
    last_error: bpy.props.StringProperty(name="Last Error", default="")


def register():
    bpy.utils.register_class(NoisemakerSettings)
    bpy.utils.register_class(NoisemakerImageInput)
    bpy.utils.register_class(NoisemakerLiveInstance)
    bpy.types.Scene.noisemaker = bpy.props.PointerProperty(type=NoisemakerSettings)
    bpy.types.Scene.noisemaker_instances = bpy.props.CollectionProperty(type=NoisemakerLiveInstance)
    bpy.types.Scene.noisemaker_active_index = bpy.props.IntProperty(name="Active Noisemaker", default=0,
                                                                     min=0)


def unregister():
    del bpy.types.Scene.noisemaker_active_index
    del bpy.types.Scene.noisemaker_instances
    del bpy.types.Scene.noisemaker
    bpy.utils.unregister_class(NoisemakerLiveInstance)
    bpy.utils.unregister_class(NoisemakerImageInput)
    bpy.utils.unregister_class(NoisemakerSettings)
