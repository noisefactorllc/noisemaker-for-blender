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
            if step.get("temp") == step_index:
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


def replace_effect(compiled, step_index, new_effect_name, new_args=None, options=None):
    """Port of ``replaceEffect``. Returns {success, program?|error?}."""
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

    if effect_namespace and effect_namespace not in new_program.get("searchNamespaces", []):
        new_program["searchNamespaces"] = list(new_program.get("searchNamespaces", [])) + [effect_namespace]

    new_step = new_program["plans"][plan_index]["chain"][chain_index]
    new_step["op"] = resolved_new_name
    new_step["args"] = final_args
    new_step["namespace"] = {"resolved": effect_namespace} if effect_namespace else None

    return {"success": True, "program": new_program}


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
    for op_name in _ops_mod.ops().keys():
        if _check_is_starter(op_name, search_order):
            starters.append(op_name)
        else:
            non_starters.append(op_name)
    if is_starter_position:
        return {"success": True, "compatible": starters, "incompatible": non_starters}
    return {"success": True, "compatible": non_starters, "incompatible": starters}
