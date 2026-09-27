"""transform.py -- program-transform utilities (port of shaders/src/lang/transform.js).

These are NOT part of the ``compile()`` (Stage-1) pipeline -- the reference
``lang/index.js`` exports them alongside ``compile`` but ``compile`` itself only
runs lex -> parse -> validate. They operate on the *validated* program dict
returned by ``compile`` and support programmatic editing (e.g. swapping an
effect within a chain in tooling/UI). Ported for completeness/fidelity.

stdlib-only and self-contained: imports only sibling compiler modules + stdlib.
"""

from __future__ import annotations

import copy

from . import ops as _ops_mod
from . import registry as _registry_mod
from .ops import is_starter_op


def _deep_clone(obj):
    return copy.deepcopy(obj)


def _find_step_by_index(compiled, step_index):
    """Port of ``findStepByIndex``: returns dict {planIndex, chainIndex, step} or None."""
    if not compiled or not compiled.get("plans"):
        return None
    plans = compiled["plans"]
    for plan_index, plan in enumerate(plans):
        if not plan or not plan.get("chain"):
            continue
        for chain_index, step in enumerate(plan["chain"]):
            if not step.get("builtin") and step.get("temp") == step_index:
                return {"planIndex": plan_index, "chainIndex": chain_index, "step": step}
    return None


def _check_is_starter(effect_name, search_order=None):
    """Port of ``checkIsStarter``."""
    if not effect_name or not isinstance(effect_name, str):
        return False
    search_order = search_order or []
    if is_starter_op(effect_name):
        return True
    if "." not in effect_name and len(search_order) > 0:
        for ns in search_order:
            if is_starter_op("%s.%s" % (ns, effect_name)):
                return True
    return False


def _get_effect_spec(effect_name, search_order=None):
    """Port of ``getEffectSpec``."""
    if not effect_name or not isinstance(effect_name, str):
        return None
    search_order = search_order or []
    ops = _ops_mod.ops()
    if effect_name in ops:
        return ops[effect_name]
    if "." not in effect_name and len(search_order) > 0:
        for ns in search_order:
            namespaced = "%s.%s" % (ns, effect_name)
            if namespaced in ops:
                return ops[namespaced]
    return None


# ============================================================================
# Replacement preflight prediction (GAP-008; reference commit 403c2a4bf2cb)
# ============================================================================

def _get_effect_instance(resolved_name):
    """Port of ``getEffectInstance``: the effect definition for a resolved
    namespaced name, or None (never registered / lang-only usage)."""
    if not isinstance(resolved_name, str):
        return None
    return _registry_mod.get_effect(resolved_name)


def _runtime_registry_populated():
    """Port of ``runtimeRegistryPopulated``: True if at least one effect
    definition is registered (otherwise per-effect availability is unknown)."""
    return len(_registry_mod.all_effects()) > 0


def _js_typeof(value):
    """The JS ``typeof`` string for a Python value (used in type messages)."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "object"
    return "object"


def _type_matches(value, type_):
    """Port of ``typeMatches``: only clear mismatches are flagged."""
    if value is None:
        return True
    if type_ in ("float", "int", "number"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_ == "color":
        return isinstance(value, str) and value.startswith("#")
    if type_ in ("bool", "boolean"):
        return isinstance(value, bool)
    if type_ in ("surface", "tex"):
        return isinstance(value, str)
    return True


def _collect_accepted_arg_names(spec, instance, aliases):
    """Port of ``collectAcceptedArgNames``: spec args, instance globals, and
    both sides of the registered param-alias map."""
    accepted = set()
    for def_ in (spec.get("args") or []) if spec else []:
        if def_ and def_.get("name"):
            accepted.add(def_["name"])
    if instance:
        for key in (instance.get("globals") or {}).keys():
            accepted.add(key)
    for name in aliases.keys():
        accepted.add(name)
    for name in aliases.values():
        accepted.add(name)
    return accepted


def _predict_backend_support(instance, resolved_name, manifest):
    """Port of ``predictBackendSupport`` from an optional shader manifest
    (the object served at effects/manifest.json). None when unknown."""
    if not manifest or not instance or not instance.get("passes"):
        return None
    namespace = instance.get("namespace") or resolved_name.split(".")[0]
    candidates = [instance.get("name"), instance.get("func"), resolved_name.split(".")[-1]]
    entry = None
    for display_name in candidates:
        if display_name and manifest.get("%s/%s" % (namespace, display_name)):
            entry = manifest["%s/%s" % (namespace, display_name)]
            break
    if not entry:
        return {"webgl2": False, "webgpu": False}
    programs = [p.get("program") for p in instance["passes"] if p and p.get("program")]

    def cover(table):
        if not table:
            return False
        if len(programs) == 0:
            return None
        hits = [p for p in programs if p in table]
        if len(hits) == 0:
            return False
        return True if len(hits) == len(programs) else "partial"

    return {"webgl2": cover(entry.get("glsl")), "webgpu": cover(entry.get("wgsl"))}


def _predict_sampler_topology(instance):
    """Port of ``predictSamplerTopology``. None when no instance."""
    if not instance:
        return None
    internal_textures = list((instance.get("textures") or {}).keys())
    pass_inputs = []
    for pass_ in instance.get("passes") or []:
        for value in (pass_.get("inputs") or {}).values():
            if isinstance(value, str) and value not in pass_inputs:
                pass_inputs.append(value)
    return {"internalTextures": internal_textures, "passInputs": pass_inputs}


def _predict_passes_and_outputs(instance):
    """Port of ``predictPassesAndOutputs``. None when no instance."""
    if not instance:
        return None
    passes = [
        {
            "name": pass_.get("name"),
            "program": pass_.get("program"),
            "inputs": dict(pass_.get("inputs") or {}),
            "outputs": dict(pass_.get("outputs") or {}),
            "drawBuffers": pass_.get("drawBuffers"),
        }
        for pass_ in (instance.get("passes") or [])
        if pass_
    ]
    outputs = {
        "geo": instance.get("outputGeo"),
        "tex3d": instance.get("outputTex3d"),
    }
    return {"passes": passes, "outputs": outputs}


def predict_replacement(resolved_name, spec, new_args, old_instance, options=None):
    """Port of ``predictReplacement`` (GAP-008).

    Predict a candidate replacement's compatibility dimensions before
    mutation: shader availability, arguments (unknown/missing), types, ranges
    (min/max/choices), passes, outputs, sampler topology, and backend support
    (from an optional ``options['manifest']``). Dimensions whose data is
    unavailable are reported as ``None`` ("unknown"), never invented.

    Returns a prediction dict with ``issues`` (hard problems) and informative
    fields.
    """
    options = options or {}
    new_args = new_args or {}
    instance = _get_effect_instance(resolved_name)
    prediction = {
        "effect": resolved_name,
        "available": None,
        "arguments": {"unknown": [], "missing": []},
        "types": [],
        "ranges": [],
        "passes": None,
        "outputs": None,
        "samplerTopology": None,
        "backendSupport": None,
        "issues": [],
    }

    # Shader availability
    if instance:
        prediction["available"] = True
    elif _runtime_registry_populated():
        prediction["available"] = False
        prediction["issues"].append(
            {
                "dimension": "shader-availability",
                "message": "No registered effect definition for '%s'" % resolved_name,
            }
        )

    aliases = _ops_mod.get_param_aliases(resolved_name)
    accepted = _collect_accepted_arg_names(spec, instance, aliases)

    provided = new_args or {}
    provided_canonical = set(aliases.get(key, key) for key in provided.keys())
    for key in provided.keys():
        canonical = aliases.get(key, key)
        if canonical not in accepted:
            prediction["arguments"]["unknown"].append(key)
    known_defs = {}
    for def_ in (spec.get("args") or []) if spec else []:
        if def_ and def_.get("name"):
            known_defs[def_["name"]] = def_
    if instance:
        for key, def_ in (instance.get("globals") or {}).items():
            if key not in known_defs:
                known_defs[key] = def_
    for key, def_ in known_defs.items():
        if (def_ is None or def_.get("default") is None) and key not in provided_canonical:
            prediction["arguments"]["missing"].append(key)
    if prediction["arguments"]["unknown"]:
        prediction["issues"].append(
            {
                "dimension": "arguments",
                "message": "Unknown argument(s) for '%s': %s"
                % (resolved_name, ", ".join(prediction["arguments"]["unknown"])),
            }
        )

    # Type and range checks
    for key, value in provided.items():
        canonical = aliases.get(key, key)
        def_ = known_defs.get(canonical)
        if not def_:
            continue
        declared_type = def_.get("type")
        if not _type_matches(value, declared_type):
            prediction["types"].append(
                {"arg": key, "expected": declared_type, "actual": _js_typeof(value)}
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if def_.get("min") is not None and value < def_["min"]:
                prediction["ranges"].append(
                    {"arg": canonical, "value": value, "min": def_.get("min"), "max": def_.get("max")}
                )
            if def_.get("max") is not None and value > def_["max"]:
                prediction["ranges"].append(
                    {"arg": canonical, "value": value, "min": def_.get("min"), "max": def_.get("max")}
                )
        choices = def_.get("choices")
        if choices and isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed = list(choices.values())
            if value not in allowed:
                prediction["ranges"].append(
                    {"arg": canonical, "value": value, "choices": allowed}
                )
    if prediction["types"]:
        prediction["issues"].append(
            {
                "dimension": "types",
                "message": "; ".join(
                    "Argument '%s' for '%s' expects %s, got %s"
                    % (t["arg"], resolved_name, t["expected"], t["actual"])
                    for t in prediction["types"]
                ),
            }
        )
    if prediction["ranges"]:
        messages = []
        for r in prediction["ranges"]:
            if "choices" in r:
                messages.append(
                    "Argument '%s' for '%s' value %s is not one of %s"
                    % (r["arg"], resolved_name, r["value"], ", ".join(str(c) for c in r["choices"]))
                )
            else:
                messages.append(
                    "Argument '%s' for '%s' value %s outside range [%s, %s]"
                    % (r["arg"], resolved_name, r["value"], r["min"], r["max"])
                )
        prediction["issues"].append({"dimension": "ranges", "message": "; ".join(messages)})

    # Structure predictions (informative when data is available)
    passes_prediction = _predict_passes_and_outputs(instance)
    if passes_prediction is not None:
        prediction["passes"] = passes_prediction["passes"]
        prediction["outputs"] = passes_prediction["outputs"]
    topology = _predict_sampler_topology(instance)
    if topology is not None:
        prediction["samplerTopology"] = topology
        if old_instance:
            old_topology = _predict_sampler_topology(old_instance)
            if old_topology:
                prediction["samplerTopology"]["changedFrom"] = {
                    "internalTextures": old_topology["internalTextures"],
                    "passInputs": old_topology["passInputs"],
                }
    prediction["backendSupport"] = _predict_backend_support(instance, resolved_name, options.get("manifest"))

    return prediction


def replace_effect(compiled, step_index, new_effect_name, new_args=None, options=None):
    """Port of ``replaceEffect``. Returns {success, program?/prediction?|error?}."""
    new_args = new_args or {}
    options = options or {}
    if not compiled or not compiled.get("plans"):
        return {"success": False, "error": "Invalid compiled program: missing plans"}

    search_order = options.get("searchOrder") or compiled.get("searchNamespaces") or []

    location = _find_step_by_index(compiled, step_index)
    if not location:
        return {"success": False, "error": "Step with index %s not found" % step_index}

    plan_index = location["planIndex"]
    chain_index = location["chainIndex"]
    step = location["step"]
    old_effect_name = step.get("op")

    current_is_starter = _check_is_starter(old_effect_name, search_order)
    # A step is in "starter position" if it is either:
    # (a) the first step in the chain (chain_index == 0), OR
    # (b) an inline surface producer — a registered starter effect with no
    #     pipeline predecessor (from is None), which the compiler
    #     flattened into the chain as a dependency of a surface-type parameter.
    is_starter_position = chain_index == 0 or (
        current_is_starter and (step.get("from") is None)
    )
    new_is_starter = _check_is_starter(new_effect_name, search_order)

    new_spec = _get_effect_spec(new_effect_name, search_order)
    if not new_spec:
        return {"success": False, "error": "Effect '%s' not found" % new_effect_name}

    if is_starter_position and not new_is_starter:
        return {
            "success": False,
            "error": (
                "Cannot replace starter effect '%s' with non-starter effect '%s'. "
                "The first effect in a chain must be a starting effect."
                % (old_effect_name, new_effect_name)
            ),
        }
    if not is_starter_position and new_is_starter:
        return {
            "success": False,
            "error": (
                "Cannot replace non-starter effect '%s' with starter effect '%s'. "
                "Starting effects can only appear at the beginning of a chain."
                % (old_effect_name, new_effect_name)
            ),
        }

    new_program = _deep_clone(compiled)

    final_args = {}
    spec_args = new_spec.get("args") or []
    for d in spec_args:
        if d.get("default") is not None:
            final_args[d["name"]] = d["default"]

    for key, value in new_args.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not float(value).is_integer():
            final_args[key] = round(value * 1000) / 1000
        else:
            final_args[key] = value

    resolved_new_name = new_effect_name
    effect_namespace = None
    ops = _ops_mod.ops()

    if "." in new_effect_name:
        parts = new_effect_name.split(".")
        effect_namespace = parts[0]
        if new_effect_name not in ops:
            return {"success": False, "error": "Effect '%s' not found" % new_effect_name}
    else:
        for ns in search_order:
            namespaced = "%s.%s" % (ns, new_effect_name)
            if namespaced in ops:
                resolved_new_name = namespaced
                effect_namespace = ns
                break
        if not effect_namespace:
            for op_name in ops.keys():
                if op_name.endswith(".%s" % new_effect_name):
                    resolved_new_name = op_name
                    effect_namespace = op_name.split(".")[0]
                    break

    # Preflight prediction of the candidate's compatibility dimensions
    # (availability, arguments, types, ranges, passes, outputs, sampler
    # topology, backend support) BEFORE any mutation, using the resolved
    # namespaced effect name.
    prediction = predict_replacement(
        resolved_new_name,
        new_spec,
        new_args,
        _get_effect_instance(old_effect_name),
        options,
    )
    if options.get("preflight") is True and prediction["issues"]:
        messages = [issue["message"] for issue in prediction["issues"]]
        return {
            "success": False,
            "error": "Replacement preflight failed: %s" % "; ".join(messages),
            "prediction": prediction,
        }

    if effect_namespace and effect_namespace not in new_program.get("searchNamespaces", []):
        new_program["searchNamespaces"] = list(new_program.get("searchNamespaces", [])) + [effect_namespace]

    new_step = new_program["plans"][plan_index]["chain"][chain_index]
    new_step["op"] = resolved_new_name
    new_step["args"] = final_args
    new_step["namespace"] = {"resolved": effect_namespace} if effect_namespace else None

    return {"success": True, "program": new_program, "prediction": prediction}


def list_steps(compiled, options=None):
    """Port of ``listSteps``."""
    options = options or {}
    if not compiled or not compiled.get("plans"):
        return []
    search_order = options.get("searchOrder") or compiled.get("searchNamespaces") or []
    steps = []
    for plan_index, plan in enumerate(compiled["plans"]):
        if not plan or not plan.get("chain"):
            continue
        for chain_index, step in enumerate(plan["chain"]):
            if step.get("builtin"):
                continue
            is_starter = _check_is_starter(step.get("op"), search_order)
            is_starter_position = chain_index == 0 or (
                is_starter and (step.get("from") is None)
            )
            steps.append(
                {
                    "stepIndex": step.get("temp"),
                    "planIndex": plan_index,
                    "chainIndex": chain_index,
                    "effectName": step.get("op"),
                    "isStarter": is_starter,
                    "isStarterPosition": is_starter_position,
                    "canReplaceWithStarter": is_starter_position,
                    "canReplaceWithNonStarter": not is_starter_position,
                    "args": step.get("args") or {},
                }
            )
    return steps


def get_compatible_replacements(compiled, step_index, options=None):
    """Port of ``getCompatibleReplacements``."""
    options = options or {}
    if not compiled or not compiled.get("plans"):
        return {"success": False, "error": "Invalid compiled program: missing plans"}
    search_order = options.get("searchOrder") or compiled.get("searchNamespaces") or []
    location = _find_step_by_index(compiled, step_index)
    if not location:
        return {"success": False, "error": "Step with index %s not found" % step_index}
    chain_index = location["chainIndex"]
    step = location.get("step") or {}
    current_is_starter = _check_is_starter(step.get("op"), search_order)
    is_starter_position = chain_index == 0 or (
        current_is_starter and (step.get("from") is None)
    )
    starters = []
    non_starters = []
    predictions = {}
    old_instance = _get_effect_instance(step.get("op"))
    for op_name in _ops_mod.ops().keys():
        predictions[op_name] = predict_replacement(
            op_name,
            _ops_mod.ops()[op_name],
            {},
            old_instance,
            options,
        )
        if _check_is_starter(op_name, search_order):
            starters.append(op_name)
        else:
            non_starters.append(op_name)
    if options.get("preflight") is True:
        # Opt-in: move candidates whose prediction found hard issues out of
        # the compatible list, with the reason attached.
        blocked = []

        def filter_issues(names):
            ok = []
            for name in names:
                if predictions[name]["issues"]:
                    blocked.append({"effect": name, "issues": predictions[name]["issues"]})
                else:
                    ok.append(name)
            return ok

        if is_starter_position:
            return {
                "success": True,
                "compatible": filter_issues(starters),
                "incompatible": non_starters,
                "blocked": blocked,
                "predictions": predictions,
            }
        return {
            "success": True,
            "compatible": filter_issues(non_starters),
            "incompatible": starters,
            "blocked": blocked,
            "predictions": predictions,
        }
    # Default (unchanged) classification, plus per-candidate predictions so
    # callers can inspect availability, arguments, types, ranges, passes,
    # outputs, sampler topology, and backend support before mutating.
    if is_starter_position:
        return {"success": True, "compatible": starters, "incompatible": non_starters, "predictions": predictions}
    return {"success": True, "compatible": non_starters, "incompatible": starters, "predictions": predictions}
