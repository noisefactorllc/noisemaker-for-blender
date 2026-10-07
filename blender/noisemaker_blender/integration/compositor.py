"""Stock compositor Image consumers for coherent published float Images."""
from .materials import managed_node


def attach_compositor(instance, node_tree, image):
    if node_tree.bl_idname != 'CompositorNodeTree':
        raise TypeError('A compositor node tree is required')
    return managed_node(instance, node_tree, image, 'CompositorNodeImage')
