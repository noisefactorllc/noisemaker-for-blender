"""Stable Blender-owned live configuration; GPU sessions are rebuilt, not saved."""
from __future__ import annotations
from pathlib import Path
import uuid

OUTPUT_OWNER = "noisemaker_owner"
OUTPUT_IMAGE_ID = "noisemaker_image_id"


def _images(images):
    if images is not None:
        return tuple(images)
    import bpy
    return tuple(bpy.data.images)


def _owned_images(config, images):
    owner = config.instance_id
    matches = [image for image in images if image.get(OUTPUT_OWNER) == owner]
    if len(matches) > 1:
        raise ValueError("multiple output Images claim instance %s" % owner)
    return matches


def _writable_output_config(config):
    scene = getattr(config, "id_data", None)
    if getattr(scene, "library", None) is not None or getattr(config, "library", None) is not None:
        raise ValueError("linked live configuration is read-only")
    check = getattr(config, "is_property_readonly", None)
    if callable(check) and check("output_image_ref"):
        raise ValueError("live output reference is read-only")


def resolve_output_image(config, *, images=None):
    """Resolve the saved scalar reference without reading an Image RNA pointer."""
    reference = getattr(config, "output_image_ref", "")
    owned = _owned_images(config, _images(images))
    if not reference:
        if owned:
            raise ValueError("owned output Image has no saved reference for instance %s" %
                             config.instance_id)
        return None
    if not owned:
        return None
    image = owned[0]
    if image.get(OUTPUT_IMAGE_ID) != reference:
        raise ValueError("saved output Image identity does not match instance %s" %
                         config.instance_id)
    if image.library is not None or not image.is_float:
        raise ValueError("owned output Image must be a local float Image")
    return image


def assign_output_image(config, image, *, images=None):
    """Persist only an Image UUID; ordinary consumers retain their Image links."""
    _writable_output_config(config)
    candidates = _images(images)
    if image is None:
        previous = resolve_output_image(config, images=candidates)
        old_reference = getattr(config, "output_image_ref", "")
        config.output_image_ref = ""
        if previous is not None:
            try:
                del previous[OUTPUT_OWNER]
            except Exception:
                config.output_image_ref = old_reference
                raise
        return
    if image.library is not None or not image.is_float:
        raise ValueError("output Image must be local and float")
    if image.get(OUTPUT_OWNER) != config.instance_id:
        raise ValueError("output Image belongs to a different instance")
    owned = _owned_images(config, candidates)
    if not owned or owned[0] is not image:
        raise ValueError("output Image is not in the current Image collection")
    image_id = image.get(OUTPUT_IMAGE_ID)
    if image_id is not None and (not isinstance(image_id, str) or not image_id):
        raise ValueError("output Image has an invalid identity")
    if not image_id:
        image_id = uuid.uuid4().hex
        old_reference = getattr(config, "output_image_ref", "")
        config.output_image_ref = image_id
        try:
            image[OUTPUT_IMAGE_ID] = image_id
        except Exception:
            config.output_image_ref = old_reference
            raise
        return
    config.output_image_ref = image_id


def migrate_legacy_output_refs(scenes, *, images=None):
    """Remove old saved Image IDProperties before live graph construction."""
    migrated = 0
    eligible = []
    errors = []
    for scene in scenes:
        for config in getattr(scene, "noisemaker_instances", ()):
            keys = getattr(config, "keys", None)
            if not callable(keys) or "output_image" not in keys():
                continue
            if (getattr(scene, "library", None) is not None
                    or getattr(config, "library", None) is not None):
                errors.append("linked legacy output reference is read-only")
                continue
            try:
                _writable_output_config(config)
                # Delete every writable raw pointer before validating any owner.
                del config["output_image"]
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))
                continue
            eligible.append(config)
            migrated += 1
    for config in eligible:
        try:
            owned = _owned_images(config, _images(images))
            if owned and not getattr(config, "output_image_ref", ""):
                image = owned[0]
                if image.library is not None or not image.is_float:
                    raise ValueError("legacy output Image must be local and float")
                image_id = image.get(OUTPUT_IMAGE_ID)
                if image_id is not None and (not isinstance(image_id, str) or not image_id):
                    raise ValueError("legacy output Image has an invalid identity")
                if not image_id:
                    image_id = uuid.uuid4().hex
                    image[OUTPUT_IMAGE_ID] = image_id
                config.output_image_ref = image_id
        except Exception as exc:
            errors.append("%s: %s" % (type(exc).__name__, exc))
    if errors:
        raise ValueError("; ".join(errors))
    return migrated


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
                # Do not call hasattr: it reads this nested RNA pointer, the
                # same conversion that crashed live publisher reconstruction.
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
