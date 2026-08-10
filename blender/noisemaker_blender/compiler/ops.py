"""ops.py -- op/enum/alias registry derived from the effect-definition registry.

The reference validator consumes several module-level registries that are
populated at effect-registration time in ``shaders/src/renderer/canvas.js``
(``registerEffectWithRuntime`` + ``registerStarterOpForEffect``):

  * ``ops``           -- ``{ 'ns.func': { name, args: [...] } }`` where each arg
                         is derived from the effect's ``globals`` entry.
  * ``STARTER_OPS``   -- set of starter op names (bare ``func`` and ``ns.func``),
                         where "starter" == ``isStarterEffect`` (no passes, or no
                         pass input references a pipeline input).
  * ``enums``         -- nested choice tree merged from every effect's
                         ``globals[*].choices`` under ``ns.func.key``.
  * ``param_aliases`` -- ``{ 'ns.func': { oldName: newName } }``
  * ``effect_aliases``-- ``{ 'ns.func': replacementName }`` (only when an effect
                         is ``hidden`` and has ``deprecatedBy``).

This module ports that registration logic verbatim and drives it from
``registry.py`` (the normalized effect-definition loader). It is the bridge
between the port's effect-def JSON and the reference validator's runtime state.

Determinism: effects are processed in the same sorted ``(namespace, func)`` order
``registry.load()`` uses, so bare-name collisions (``noise``, ``noise3d``) resolve
identically run-to-run. The validator resolves ops via the search order using
fully-qualified ``ns.func`` keys, so bare-name collision order never affects
validated output for namespaced lookups.

stdlib-only and self-contained: imports only sibling compiler modules + stdlib.
"""

from __future__ import annotations

import threading

from . import registry
from .lang_data import STD_ENUMS

# Pipeline-input surface names; a pass referencing any of these (in pass.inputs)
# means the effect needs an input -> NOT a starter.
#
# This is the EXACT set used by the golden-generating oracle
# (tools/dump-compile.mjs bootstrapReference): ['inputTex','inputTex3d','src',
# 'o0','o1']. canvas.js's isStarterEffect uses a slightly different set
# (inputTex/inputTex3d/o0..o7); the two agree on every effect in the catalog
# (verified: zero divergence across all 184 defs, since no pass.inputs value is
# 'src' or 'o2'..'o7'), but we match the oracle that produced the goldens.
_PIPELINE_INPUTS = frozenset(["inputTex", "inputTex3d", "src", "o0", "o1"])

_OPS: dict[str, dict] = {}
_STARTER_OPS: set[str] = set()
_ENUMS: dict[str, dict] = {}
_PARAM_ALIASES: dict[str, dict] = {}
_EFFECT_ALIASES: dict[str, str] = {}

_BUILT = False
_LOCK = threading.Lock()


# --- isValidIdentifier / sanitizeEnumName (canvas.js) -------------------------
def _is_valid_identifier(name) -> bool:
    """Port of ``isValidIdentifier``: ``/^[a-zA-Z_$][a-zA-Z0-9_$]*$/``."""
    if not isinstance(name, str) or not name:
        return False
    first = name[0]
    if not (first.isalpha() or first in "_$"):
        return False
    for ch in name[1:]:
        if not (ch.isalnum() or ch in "_$"):
            return False
    # JS ``isalpha``/``isalnum`` here are ASCII; Python str.isalpha accepts
    # unicode letters, so restrict to ASCII to match the regex exactly.
    return all(ord(ch) < 128 for ch in name)


def _sanitize_enum_name(name: str):
    """Port of ``sanitizeEnumName`` (canvas.js).

    "Cell Scale" -> "CellScale"; strips invalid chars; returns None if the
    result is not a valid identifier.
    """
    # result = name.replace(/\s+(.)/g, (_, c) => c.toUpperCase()).replace(/\s+/g, '')
    result_chars = []
    i = 0
    n = len(name)
    while i < n:
        ch = name[i]
        if ch.isspace():
            # consume the whole run of whitespace
            j = i
            while j < n and name[j].isspace():
                j += 1
            if j < n:
                # uppercase the char following the whitespace run
                result_chars.append(name[j].upper())
                i = j + 1
            else:
                # trailing whitespace run -> dropped
                i = j
        else:
            result_chars.append(ch)
            i += 1
    result = "".join(result_chars)
    # result = result.replace(/[^a-zA-Z0-9_]/g, '')
    result = "".join(ch for ch in result if (ch.isascii() and (ch.isalnum() or ch == "_")))
    if not _is_valid_identifier(result):
        return None
    return result


def _is_starter_effect(definition: dict) -> bool:
    """Port of ``isStarterEffect`` driven by an effect definition dict."""
    passes = definition.get("passes") or []
    if len(passes) == 0:
        return True
    for pass_ in passes:
        inputs = pass_.get("inputs")
        if inputs and any(v in _PIPELINE_INPUTS for v in inputs.values()):
            return False
    return True


def _merge_choice_tree(target: dict, source: dict) -> None:
    """Port of enums.deepMerge for the choice-tree shape we register.

    The reference ``mergeIntoEnums`` deep-merges nested plain objects but assigns
    (does not recurse into) an enum-entry leaf carrying both ``type`` and ``value``.
    Our source tree is ``{ns: {func: {key: {choiceName: {type:'Number', value}}}}}``
    so the namespace/func/key levels are merged and the leaf enum entries are
    assigned -- which is exactly what deepMerge does. Checking only for a
    ``type`` key is insufficient because an effect may itself have a choice
    parameter named ``type``; that container must still merge with sibling
    parameter trees such as ``volumeSize``.
    """
    for key, source_val in source.items():
        target_val = target.get(key)
        if (
            isinstance(source_val, dict)
            and isinstance(target_val, dict)
            and not ("type" in source_val and "value" in source_val)
        ):
            _merge_choice_tree(target_val, source_val)
        else:
            target[key] = source_val


def _register_effect(definition: dict) -> None:
    """Port of ``registerEffectWithRuntime`` + ``registerStarterOpForEffect``."""
    namespace = definition.get("namespace")
    func = definition.get("func")
    if not namespace or not func:
        return

    op_key = "%s.%s" % (namespace, func)

    # --- build args from globals (preserve insertion order) -------------------
    args = []
    globals_ = definition.get("globals") or {}
    for key, spec in globals_.items():
        enum_path = spec.get("enum") or spec.get("enumPath")
        choices = spec.get("choices")
        if choices and not enum_path:
            enum_path = "%s.%s.%s" % (namespace, func, key)
            key_tree = {}
            for name, val in choices.items():
                if name.endswith(":"):
                    continue
                key_tree[name] = {"type": "Number", "value": val}
                sanitized = _sanitize_enum_name(name)
                if sanitized and sanitized != name:
                    key_tree[sanitized] = {"type": "Number", "value": val}
            # Merge into the running enum tree exactly like mergeIntoEnums would.
            _merge_choice_tree(_ENUMS, {namespace: {func: {key: key_tree}}})

        spec_type = spec.get("type")
        arg = {
            "name": key,
            "type": "color" if spec_type == "vec4" else spec_type,
            "default": spec.get("default"),
            "enum": enum_path,
            "enumPath": enum_path,
            "min": spec.get("min"),
            "max": spec.get("max"),
            "uniform": spec.get("uniform"),
            "choices": choices,
        }
        args.append(arg)

    _OPS[op_key] = {"name": func, "args": args}

    # --- param aliases / effect aliases ---------------------------------------
    # INTENTIONALLY NOT REGISTERED.
    #
    # The Stage-1 contract is defined by the golden-generating oracle
    # (tools/dump-compile.mjs ``bootstrapReference``), which registers effects,
    # ops, starter ops, and enums -- but does NOT call registerParamAliases or
    # registerEffectAlias. Consequently, in the reference compile() output:
    #   * a deprecated param NAME (e.g. ``noiseType``) is treated as an UNKNOWN
    #     argument -> S001 (not remapped, no S007); its value is dropped and the
    #     canonical param keeps its default.
    #   * a deprecated effect emits NO S008.
    # (canvas.js DOES register both at runtime, but that path did not produce the
    # goldens.) Populating ``_PARAM_ALIASES``/``_EFFECT_ALIASES`` here would make
    # ``resolve_param_aliases``/``check_effect_alias`` diverge from the contract,
    # so they are deliberately left empty. The defs' ``paramAliases`` /
    # ``deprecatedBy`` fields are still read by the expander stage separately.

    # --- starter ops ----------------------------------------------------------
    if _is_starter_effect(definition):
        _STARTER_OPS.add(func)
        _STARTER_OPS.add(op_key)


def _build(force: bool = False) -> None:
    global _BUILT
    with _LOCK:
        if _BUILT and not force:
            return
        _OPS.clear()
        _STARTER_OPS.clear()
        _ENUMS.clear()
        _PARAM_ALIASES.clear()
        _EFFECT_ALIASES.clear()
        # Seed the enum tree with the standard enums (mergeIntoEnums(stdEnums)).
        _merge_choice_tree(_ENUMS, _deepcopy_tree(STD_ENUMS))
        for definition in registry.all_effects():
            _register_effect(definition)
        _BUILT = True


def _deepcopy_tree(node):
    if isinstance(node, dict):
        return {k: _deepcopy_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_deepcopy_tree(v) for v in node]
    return node


def _ensure_built() -> None:
    if not _BUILT:
        _build()


# --- public accessors (the validator's view of the registries) ----------------
def ops() -> dict:
    _ensure_built()
    return _OPS


def get_op(name: str):
    _ensure_built()
    return _OPS.get(name)


def has_op(name: str) -> bool:
    _ensure_built()
    return name in _OPS


def enums() -> dict:
    _ensure_built()
    return _ENUMS


def is_starter_op(name) -> bool:
    """Port of ``validator.isStarterOp``."""
    _ensure_built()
    if not isinstance(name, str):
        return False
    # Force particles to be non-starter (workaround for stale manifest/cache).
    if name == "particles" or name == "render.particles":
        return False
    if name in _STARTER_OPS:
        return True
    parts = name.split(".")
    if len(parts) > 1:
        canonical = parts[-1]
        if canonical in _STARTER_OPS:
            for op in _STARTER_OPS:
                if op.endswith("." + canonical):
                    # A namespaced starter exists but our exact name was not in
                    # the set -> we are not a starter.
                    return False
            return True
    return False


def resolve_param_aliases(op_name: str, kwargs: dict):
    """Port of ``paramAliases.resolveParamAliases`` (mutates ``kwargs``).

    Returns the list of deprecation-warning strings.
    """
    from .lang_data import param_alias_warning

    _ensure_built()
    warnings = []
    aliases = _PARAM_ALIASES.get(op_name)
    if not aliases:
        return warnings
    for old_name in list(aliases.keys()):
        if old_name not in kwargs:
            continue
        new_name = aliases[old_name]
        if new_name not in kwargs:
            kwargs[new_name] = kwargs[old_name]
        del kwargs[old_name]
        warnings.append(param_alias_warning(old_name, new_name))
    return warnings


def check_effect_alias(op_name: str):
    """Port of ``effectAliases.checkEffectAlias``. Returns a warning or None."""
    from .lang_data import effect_alias_warning

    _ensure_built()
    new_name = _EFFECT_ALIASES.get(op_name)
    if not new_name:
        return None
    return effect_alias_warning(op_name, new_name)


def rebuild() -> None:
    """Force a rebuild (mainly for tests / registry reloads)."""
    _build(force=True)
