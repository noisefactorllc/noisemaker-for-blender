"""registry.py -- effect-definition registry for the in-Blender DSL->graph compiler.

Loads the NORMALIZED effect-definition JSON files emitted by
``tools/convert-defs-blender.mjs`` into ``effects/<namespace>/<func>.json`` and
registers each under the same lookup-key forms the reference engine uses, so the
ported validator (stage 3) and expander (stage 4) can resolve an op by any of:

  * ``func``          -- bare function name (e.g. ``noise``)
  * ``namespace.func``-- dotted, fully-qualified (e.g. ``synth.noise``)
  * ``namespace/func``-- slash form (e.g. ``synth/noise``)

This mirrors the registration performed in ``tools/export-graph.mjs``
``bootstrapReference`` (which registers ``func``, ``ns.func``, ``ns/name`` and
``ns.name``). Every reference effect has ``dirname == func``, so ``ns/name`` and
``ns.name`` collapse to ``ns/func`` and ``ns.func`` -- the three distinct forms
above.

The reference's bare-``func`` registry is last-writer-wins (a ``Map.set``). Two
funcs collide across namespaces (``noise`` in classicNoisedeck + synth;
``noise3d`` in classicNoisedeck + synth3d). We register effects in sorted
(namespace, func) order so the winner is deterministic; consumers that care about
the namespace MUST resolve via the dotted/slash form (which is what the expander
does -- it calls ``get_effect`` with the fully-qualified op name).

stdlib-only and self-contained: locates ``effects/`` relative to THIS file (the
addon package), not via any ``..``/external path or environment variable.
"""

from __future__ import annotations

import json
import os
import threading

# effects/ lives as a sibling of this package's ``compiler/`` dir:
#   blender/noisemaker_blender/compiler/registry.py  (this file)
#   blender/noisemaker_blender/effects/<ns>/<func>.json
_COMPILER_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_COMPILER_DIR)            # noisemaker_blender/
EFFECTS_DIR = os.path.join(_PACKAGE_DIR, "effects")

# Module-level registry. Keyed by every lookup form -> the same definition dict.
_REGISTRY: dict[str, dict] = {}
# Canonical list of definitions in deterministic (namespace, func) order. Each
# entry appears exactly once here (unlike _REGISTRY, which has multiple keys per
# effect). This is the authoritative set for iteration/counting.
_DEFINITIONS: list[dict] = []
_LOADED = False
_LOCK = threading.Lock()


def _key_forms(namespace: str, func: str) -> tuple[str, str, str]:
    """The three lookup keys an effect is registered under."""
    return (func, "%s.%s" % (namespace, func), "%s/%s" % (namespace, func))


def _register(definition: dict) -> None:
    """Register one definition under all of its lookup-key forms.

    Bare-``func`` is last-writer-wins (matches the reference Map). The dotted and
    slash forms are unique per effect, so they never clobber another effect.
    """
    namespace = definition.get("namespace")
    func = definition.get("func")
    if not namespace or not func:
        return
    for key in _key_forms(namespace, func):
        _REGISTRY[key] = definition


def load(force: bool = False) -> int:
    """Load and register every effects/<ns>/<func>.json. Idempotent.

    Returns the number of distinct effect definitions registered.
    """
    global _LOADED
    with _LOCK:
        if _LOADED and not force:
            return len(_DEFINITIONS)

        _REGISTRY.clear()
        _DEFINITIONS.clear()

        if not os.path.isdir(EFFECTS_DIR):
            raise FileNotFoundError(
                "effects directory not found: %s (run tools/convert-defs-blender.mjs "
                "to generate the normalized effect definitions)" % EFFECTS_DIR
            )

        # Walk in sorted (namespace, func) order for deterministic collision
        # resolution and stable iteration.
        for namespace in sorted(os.listdir(EFFECTS_DIR)):
            ns_dir = os.path.join(EFFECTS_DIR, namespace)
            if not os.path.isdir(ns_dir):
                continue
            for filename in sorted(os.listdir(ns_dir)):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(ns_dir, filename)
                with open(path, "r", encoding="utf-8") as fh:
                    definition = json.load(fh)
                # Trust the JSON's own namespace/func; fall back to the path.
                definition.setdefault("namespace", namespace)
                definition.setdefault("func", filename[: -len(".json")])
                _DEFINITIONS.append(definition)
                _register(definition)

        _LOADED = True
        return len(_DEFINITIONS)


def _ensure_loaded() -> None:
    if not _LOADED:
        load()


def get_effect(key: str):
    """Look up an effect definition by any registered key form.

    Accepts the bare ``func``, ``namespace.func``, or ``namespace/func``. Returns
    the normalized definition dict, or ``None`` if no effect is registered under
    ``key`` (matching the reference ``getEffect`` Map semantics).
    """
    _ensure_loaded()
    return _REGISTRY.get(key)


def has_effect(key: str) -> bool:
    """True if any effect is registered under ``key``."""
    _ensure_loaded()
    return key in _REGISTRY


def all_effects() -> list[dict]:
    """All distinct effect definitions, in deterministic (namespace, func) order."""
    _ensure_loaded()
    return list(_DEFINITIONS)


def registered_keys() -> list[str]:
    """Every lookup key currently registered (sorted). Mostly for diagnostics."""
    _ensure_loaded()
    return sorted(_REGISTRY)


def effect_count() -> int:
    """Number of distinct effect definitions registered."""
    _ensure_loaded()
    return len(_DEFINITIONS)
