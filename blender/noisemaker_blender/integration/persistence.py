"""Stable Blender-owned live configuration; GPU sessions are rebuilt, not saved."""
from __future__ import annotations
from pathlib import Path
import uuid


def ensure_unique_ids(scenes):
    """Repair local duplicates while reserving linked read-only identities."""
    scenes = tuple(scenes)
    def read_only(scene, instance):
        if getattr(scene, "library", None) is not None or getattr(instance, "library", None) is not None:
            return True
        check = getattr(instance, "is_property_readonly", None)
        return bool(check("instance_id")) if callable(check) else False

    seen = {instance.instance_id for scene in scenes
            for instance in getattr(scene, "noisemaker_instances", ())
            if read_only(scene, instance) and getattr(instance, "instance_id", "")}
    changed = []
    for scene in scenes:
        for instance in getattr(scene, "noisemaker_instances", ()):
            if read_only(scene, instance):
                continue
            identity = getattr(instance, "instance_id", "")
            if not identity or identity in seen:
                identity = uuid.uuid4().hex
                instance.instance_id = identity
                if hasattr(instance, "output_image"):
                    instance.output_image = None
                changed.append(instance)
            seen.add(identity)
    return tuple(changed)


def create_instance(scene, program, name="Noisemaker"):
    collection = getattr(scene, "noisemaker_instances", None)
    if collection is None or not hasattr(collection, "add"):
        raise TypeError("scene has no registered Noisemaker instance collection")
    source = getattr(program, "source", program)
    if not isinstance(source, str):
        raise TypeError("program must expose source text")
    instance = collection.add()
    instance.instance_id = uuid.uuid4().hex
    instance.name = name
    instance.source_mode = "INLINE"
    instance.source = source
    instance.live_enabled = False
    instance.paused = False
    return instance


def instance_for_id(scene, instance_id):
    for instance in getattr(scene, "noisemaker_instances", ()):
        if instance.instance_id == instance_id:
            return instance
    raise KeyError(instance_id)


def source_for_instance(instance, *, max_chars=2_000_000):
    """Read only the selected source and reject oversized live programs."""
    mode = getattr(instance, "source_mode", None)
    if mode == "INLINE":
        source = instance.source
    elif mode == "TEXT":
        text = getattr(instance, "text", None)
        if text is None:
            raise ValueError("select a DSL Text block")
        source = text.as_string()
    elif mode == "FILE":
        filepath = getattr(instance, "filepath", "")
        if not filepath:
            raise ValueError("select a DSL file")
        try:
            import bpy
            filepath = bpy.path.abspath(filepath)
        except ImportError:
            pass
        with Path(filepath).open("r", encoding="utf-8") as stream:
            source = stream.read(max_chars + 1)
    else:
        raise ValueError("invalid DSL source mode")
    if len(source) > max_chars:
        raise ValueError("DSL source exceeds live size limit")
    return source


def pack_outputs_before_save(scenes):
    """Refresh packed binary pixels for opted or previously packed owned Images.

    This runs in Blender's save_pre handler after live output publication, not
    during each frame. Unowned and linked Images are never modified.
    """
    packed = 0
    for scene in scenes:
        for config in getattr(scene, "noisemaker_instances", ()):
            image = getattr(config, "output_image", None)
            if image is None or not (getattr(config, "pack_output", False)
                                     or getattr(image, "packed_file", None) is not None):
                continue
            if (getattr(image, "library", None) is not None or not getattr(image, "is_float", False)
                    or image.get("noisemaker_owner") != config.instance_id):
                continue
            image.pack()
            packed += 1
    return packed


def set_image_binding(scene, config, binding, image):
    """Persist one still-Image reference on a local scene-owned instance."""
    if getattr(scene, "library", None) is not None or getattr(config, "library", None) is not None:
        raise ValueError("linked live configuration is read-only")
    # CollectionProperty is read-only as an RNA assignment even on local
    # instances; its elements remain mutable through add/remove.
    if not isinstance(binding, str) or not binding:
        raise ValueError("input binding name is required")
    collection = config.input_bindings
    matches = [index for index, item in enumerate(collection) if item.binding_name == binding]
    if len(matches) > 1:
        raise ValueError("duplicate persisted input binding %s" % binding)
    if image is None:
        if matches:
            collection.remove(matches[0])
        return None
    if getattr(image, "source", None) in ("MOVIE", "SEQUENCE"):
        raise ValueError("movie/sequence input needs an exact-frame runtime provider")
    item = collection[matches[0]] if matches else collection.add()
    item.binding_name = binding
    item.image = image
    return item
