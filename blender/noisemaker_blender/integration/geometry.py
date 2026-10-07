"""Stock Geometry Nodes sampling of a published procedural Image."""
from .materials import managed_node


def attach_geometry_image(instance, node_tree, image):
    if node_tree.bl_idname != 'GeometryNodeTree':
        raise TypeError('A Geometry Nodes tree is required')
    return managed_node(instance, node_tree, image, 'GeometryNodeImageTexture')
