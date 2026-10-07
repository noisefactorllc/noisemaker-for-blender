"""Owned stock shader nodes for procedural Images; unrelated nodes stay untouched."""

_MARKER = 'noisemaker_instance'


def identity(instance):
    value = instance if isinstance(instance, str) else getattr(instance, 'instance_id', None)
    if not isinstance(value, str) or not value:
        raise ValueError('A stable Noisemaker instance identity is required')
    return value


def require_local(datablock):
    if getattr(datablock, 'library', None) is not None:
        raise ValueError('Linked data must be made local or overridden before attaching a consumer')


def managed_node(instance, tree, image, node_type):
    """Create/update one stock image node without replacing any consumer links."""
    require_local(tree)
    owner = identity(instance)
    node = next((item for item in tree.nodes
                 if item.bl_idname == node_type and item.get(_MARKER) == owner), None)
    if node is None:
        node = tree.nodes.new(node_type)
        node[_MARKER] = owner
        node.label = 'Noisemaker'
    if node_type == 'GeometryNodeImageTexture':
        node.inputs['Image'].default_value = image
    else:
        node.image = image
    return node


def attach_material(instance, material, image):
    """Return a functional Image Texture node with Color/Alpha/Vector sockets.

    The caller selects the destination socket. Repeated attachment reuses the node
    and its links, and never replaces an existing material output or shader.
    """
    require_local(material)
    material.use_nodes = True
    return managed_node(instance, material.node_tree, image, 'ShaderNodeTexImage')


def attach_world(instance, world, image):
    """Return a stock environment texture; the caller chooses its mapping/links."""
    require_local(world)
    world.use_nodes = True
    return managed_node(instance, world.node_tree, image, 'ShaderNodeTexEnvironment')
