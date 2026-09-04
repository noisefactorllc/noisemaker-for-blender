"""validator.py -- Stage-1 semantic validator (port of shaders/src/lang/validator.js).

``validate(ast)`` consumes the parser AST and produces the validated/transformed
program that ``compile()`` returns and the expander consumes:

    { plans, diagnostics, render, vars, searchNamespaces, trailingComments? }

It flattens each chain statement into a list of steps with temporary surface
indices, resolves params against each effect's arg spec (enum/choice/member
resolution, surface refs, color/vec/boolean coercion, default injection,
deprecated-alias remap), expands subchains into begin/end markers, injects
built-in ``_read``/``_write``/``_read3d``/``_write3d``/``prev`` steps, and emits
diagnostics (S001/S002/S003/S004/S005/S006/S007/S008).

This is a faithful, behavior-preserving translation of the reference. The only
branches that cannot be reproduced 1:1 are the ones that build a live runtime
closure from a ``Func`` node (``new Function(...)``) or a state-value reference
(``{fn: state => ...}``): JS cannot be evaluated here. Those produce the same
*serialized* value the reference does under ``JSON.stringify`` (the function is
dropped, leaving only the JSON-able fields) -- which is what the parity gate
compares. None of these appear in the corpus.

stdlib-only and self-contained: imports only sibling compiler modules + stdlib.
"""

from __future__ import annotations

import copy
import math
import re

from . import ops as _ops_mod
from .lang_data import (
    DIAGNOSTICS,
    STD_ENUMS,
    apply_enum_prefix,
    normalize_member_path,
    path_starts_with,
)
from .string_literals import decode_json_string_literal_content

# A sentinel distinguishing "argument absent" (JS ``undefined``) from an explicit
# ``None`` value. Mirrors JS where ``call.args[i]`` past the end is ``undefined``.
_UNDEF = object()

_STATE_SURFACES = frozenset(["time", "frame", "mouse", "resolution", "seed", "a"])
_STATE_VALUES = frozenset(
    [
        "time", "frame", "mouse", "resolution", "seed", "a",
        "u1", "u2", "u3", "u4", "s1", "s2", "b1", "b2", "a1", "a2", "deltaTime",
    ]
)
_SURFACE_PASSTHROUGH_CALLS = frozenset(["read"])

_ALLOWED_STRING_PARAMS = frozenset(
    [
        "text.text",
        "text.font",
        "text.justify",
        "text.style",
        "midi.name",
        "midi.id",
    ]
)

_VOL_RE = re.compile(r"^vol[0-7]$")
_GEO_RE = re.compile(r"^geo[0-7]$")


def _to_boolean(value):
    """Port of ``toBoolean``: numbers -> ``!= 0``; else JS truthiness."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _js_truthy(value)


def _js_truthy(value):
    """Approximate JS truthiness for the node/value shapes we encounter."""
    if value is None or value is _UNDEF:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return len(value) > 0
    # objects/arrays are always truthy in JS
    return True


def clamp(value, vmin, vmax):
    """Port of ``clamp``."""
    if isinstance(vmin, (int, float)) and not isinstance(vmin, bool) and value < vmin:
        return vmin
    if isinstance(vmax, (int, float)) and not isinstance(vmax, bool) and value > vmax:
        return vmax
    return value


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _to_surface(arg):
    """Port of ``toSurface``."""
    if not arg or not isinstance(arg, dict):
        return None
    t = arg.get("type")
    if t == "OutputRef":
        return {"kind": "output", "name": arg.get("name")}
    if t == "SourceRef":
        return {"kind": "source", "name": arg.get("name")}
    if t == "XyzRef":
        return {"kind": "xyz", "name": arg.get("name")}
    if t == "VelRef":
        return {"kind": "vel", "name": arg.get("name")}
    if t == "RgbaRef":
        return {"kind": "rgba", "name": arg.get("name")}
    if t == "MeshRef":
        return {"kind": "mesh", "name": arg.get("name")}
    if t == "Ident" and arg.get("name") == "none":
        return {"kind": "output", "name": "none"}
    if t == "Ident" and arg.get("name") in _STATE_SURFACES:
        return {"kind": "state", "name": arg.get("name")}
    return None


def validate(ast):
    """Port of ``validate(ast)`` -> validated program dict."""
    ops = _ops_mod.ops()
    enums = _ops_mod.enums()

    diagnostics_list = []

    def extract_identifier_name(node):
        if not node:
            return None
        if not isinstance(node, dict):
            return None
        t = node.get("type")
        if t == "Ident":
            return node.get("name")
        if t == "Member" and isinstance(node.get("path"), list):
            return ".".join(node["path"])
        if t == "Call":
            return node.get("name")
        if t == "Func" and node.get("src"):
            src = node["src"]
            return "{%s%s}" % (src[:30], "..." if len(src) > 30 else "")
        if node.get("name"):
            return node.get("name")
        if node.get("value") is not None:
            return _js_string(node.get("value"))
        return "[%s]" % (node.get("type") or "unknown")

    def push_diag(code, node, message=_UNDEF):
        if message is _UNDEF:
            message = DIAGNOSTICS[code]["message"]
        enriched_message = message
        ident_name = extract_identifier_name(node)
        if ident_name and ident_name not in message and "'" not in message:
            enriched_message = "%s: '%s'" % (message, ident_name)
        location = None
        loc = node.get("loc") if isinstance(node, dict) else None
        if loc:
            # The reference reads node.loc.column, but the parser emits 'col';
            # ``column`` is therefore undefined and dropped by JSON.stringify,
            # leaving only ``line``.
            location = {"line": loc.get("line")}
            col = loc.get("column", _UNDEF)
            if col is not _UNDEF:
                location["column"] = col
        diag = {
            "code": code,
            "message": enriched_message,
            "severity": DIAGNOSTICS[code]["severity"],
        }
        node_id = node.get("id") if isinstance(node, dict) else None
        if node_id is not None:
            diag["nodeId"] = node_id
        if location is not None:
            diag["location"] = location
        if ident_name is not None:
            diag["identifier"] = ident_name
        diagnostics_list.append(diag)

    plans = []
    render = ast["render"]["name"] if ast.get("render") else None
    temp_index = [0]  # boxed so nested closures can mutate

    program_search_order = None
    namespace_decl = ast.get("namespace")
    if isinstance(namespace_decl, dict):
        program_search_order = namespace_decl.get("searchOrder")
    if not program_search_order or len(program_search_order) == 0:
        raise ValueError(
            "Missing required 'search' directive. Every program must start with "
            "'search <namespace>, ...' to specify namespace search order."
        )

    symbols = {}

    def resolve_enum(path):
        if not isinstance(path, list) or len(path) == 0:
            return _UNDEF
        head = path[0]
        rest = path[1:]
        if head in symbols:
            cur = symbols[head]
            if isinstance(cur, dict) and cur.get("type") in ("Number", "Boolean"):
                cur = cur.get("value")
        elif head in enums:
            cur = enums[head]
        elif head in STD_ENUMS:
            cur = STD_ENUMS[head]
        else:
            return _UNDEF
        for part in rest:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return _UNDEF
        if isinstance(cur, dict) and cur.get("type") in ("Number", "Boolean"):
            return cur.get("value")
        return cur

    def clone(node):
        if isinstance(node, (dict, list)):
            return copy.deepcopy(node)
        return node

    def can_resolve_op_name(name):
        for ns in program_search_order:
            if ("%s.%s" % (ns, name)) in ops:
                return True
        return False

    def resolve_call(call):
        name = call.get("name")
        if name in symbols:
            val = symbols[name]
            if isinstance(val, dict) and val.get("type") == "Ident":
                merged = dict(call)
                merged["name"] = val.get("name")
                return merged
            if isinstance(val, dict) and val.get("type") == "Call":
                merged_args = list(val.get("args") or [])
                call_args = call.get("args") or []
                for a in call_args:
                    merged_args.append(a)
                merged_kw = dict(val["kwargs"]) if val.get("kwargs") else None
                if call.get("kwargs"):
                    merged_kw = merged_kw or {}
                    for k, v in call["kwargs"].items():
                        merged_kw[k] = v
                merged = {"type": "Call", "name": val.get("name"), "args": merged_args}
                if merged_kw is not None:
                    merged["kwargs"] = merged_kw
                if call.get("namespace"):
                    merged["namespace"] = dict(call["namespace"])
                elif val.get("namespace"):
                    merged["namespace"] = dict(val["namespace"])
                return merged
        return call

    def first_chain_call(node):
        if not isinstance(node, dict):
            return None
        if node.get("type") == "Call":
            return node
        if node.get("type") == "Chain":
            chain = node.get("chain")
            head = chain[0] if chain else None
            return head if (head and head.get("type") == "Call") else None
        return None

    def get_starter_info(node):
        if not isinstance(node, dict):
            return None
        if node.get("type") == "Call":
            name = node.get("name")
            ns = node.get("namespace")
            if ns and ns.get("resolved"):
                name = "%s.%s" % (ns["resolved"], node.get("name"))
            return {"call": node, "index": 0} if _ops_mod.is_starter_op(name) else None
        if node.get("type") == "Chain" and isinstance(node.get("chain"), list):
            chain = node["chain"]
            for i, entry in enumerate(chain):
                if entry and entry.get("type") == "Call":
                    name = entry.get("name")
                    ns = entry.get("namespace")
                    if ns and ns.get("resolved"):
                        name = "%s.%s" % (ns["resolved"], entry.get("name"))
                    if _ops_mod.is_starter_op(name):
                        return {"call": entry, "index": i}
        return None

    def is_starter_chain(node):
        if not isinstance(node, dict) or node.get("type") != "Chain":
            return False
        starter = get_starter_info(node)
        return bool(starter and starter["index"] == 0)

    def substitute(node):
        if not node:
            return node
        if not isinstance(node, dict):
            return node
        t = node.get("type")
        if t == "Ident" and node.get("name") in symbols:
            result = substitute(clone(symbols[node["name"]]))
            if isinstance(result, dict):
                result["_varRef"] = node["name"]
            return result
        if t == "Chain":
            mapped = []
            for c in node["chain"]:
                mapped_args = [substitute(a) for a in (c.get("args") or [])]
                mapped_call = {"type": "Call", "name": c.get("name"), "args": mapped_args}
                if c.get("kwargs"):
                    kw = {}
                    for k, v in c["kwargs"].items():
                        kw[k] = substitute(v)
                    mapped_call["kwargs"] = kw
                mapped.append(resolve_call(mapped_call))
            return {"type": "Chain", "chain": mapped}
        if t == "Call":
            mapped_args = [substitute(a) for a in (node.get("args") or [])]
            mapped_call = {"type": "Call", "name": node.get("name"), "args": mapped_args}
            if node.get("kwargs"):
                kw = {}
                for k, v in node["kwargs"].items():
                    kw[k] = substitute(v)
                mapped_call["kwargs"] = kw
            return resolve_call(mapped_call)
        return node

    # --- variable declarations ------------------------------------------------
    if isinstance(ast.get("vars"), list):
        for v in ast["vars"]:
            expr = substitute(clone(v.get("expr")))
            if expr and is_starter_chain(expr):
                head = first_chain_call(expr)
                if head:
                    push_diag("S006", head)
            if expr is None or (
                isinstance(expr, dict)
                and expr.get("type") == "Ident"
                and expr.get("name") in ("null", "undefined")
            ):
                push_diag("S004", v)
                continue
            if (
                isinstance(expr, dict)
                and expr.get("type") == "Ident"
                and expr.get("name") not in symbols
                and expr.get("name") not in _STATE_VALUES
                and expr.get("name") not in ops
                and not can_resolve_op_name(expr.get("name"))
            ):
                push_diag("S003", expr)
                continue
            if isinstance(expr, dict) and expr.get("type") == "Chain" and len(expr["chain"]) == 1:
                symbols[v["name"]] = expr["chain"][0]
            elif isinstance(expr, dict) and expr.get("type") == "Member":
                resolved = resolve_enum(expr["path"])
                if _is_number(resolved):
                    symbols[v["name"]] = {"type": "Number", "value": resolved}
                elif resolved is not _UNDEF:
                    symbols[v["name"]] = resolved
                else:
                    symbols[v["name"]] = expr
            else:
                symbols[v["name"]] = expr

    def eval_expr(node):
        expr = substitute(clone(node))
        if expr and is_starter_chain(expr):
            head = first_chain_call(expr)
            if head:
                push_diag("S006", head)
        if isinstance(expr, dict) and expr.get("type") == "Member":
            resolved = resolve_enum(expr["path"])
            if _is_number(resolved):
                return {"type": "Number", "value": resolved}
            if resolved is not _UNDEF:
                return resolved
        return expr

    def eval_condition(node):
        expr = eval_expr(node)
        if not expr:
            return False
        if not isinstance(expr, dict):
            return False
        t = expr.get("type")
        if t == "Number":
            return _to_boolean(expr.get("value"))
        if t == "Boolean":
            return bool(expr.get("value"))
        if t == "Func":
            # JS builds a live predicate via ``new Function``; not reproducible
            # here. Represent it structurally (no closure). Not exercised by the
            # corpus.
            return {"fn": {"_func_src": expr.get("src")}}
        if t == "Ident":
            name = expr.get("name")
            if name in symbols:
                return eval_condition(symbols[name])
            if name in _STATE_VALUES:
                return {"fn": {"_state": name}}
            push_diag("S003", expr)
            return False
        if t == "Member":
            cur = resolve_enum(expr["path"])
            if _is_number(cur):
                return _to_boolean(cur)
            if cur is not _UNDEF:
                return _to_boolean(cur)
            push_diag(
                "S001",
                expr,
                "Unknown enum path: '%s'"
                % (".".join(expr["path"]) if expr.get("path") else "unknown"),
            )
            return False
        return False

    def build_namespace_snapshot(call_namespace):
        if not call_namespace or not isinstance(call_namespace, dict):
            return None
        cn = call_namespace
        call_obj = {
            "name": cn.get("name") if isinstance(cn.get("name"), str) else None,
            "resolved": cn.get("resolved") if isinstance(cn.get("resolved"), str) else None,
            "explicit": bool(cn.get("explicit")),
            "source": cn.get("source") if isinstance(cn.get("source"), str) else None,
        }
        if isinstance(cn.get("searchOrder"), list):
            call_obj["searchOrder"] = list(cn["searchOrder"])
        if cn.get("fromOverride"):
            call_obj["fromOverride"] = True
        snapshot = {"call": call_obj}
        if cn.get("resolved"):
            snapshot["resolved"] = cn["resolved"]
        return snapshot

    def compile_chain_statement(stmt):
        chain = []
        chain_node = {"type": "Chain", "chain": stmt["chain"]}
        has_write = bool(stmt.get("write") or stmt.get("write3d"))
        if not has_write and is_starter_chain(chain_node):
            push_diag("S006", stmt["chain"][0])

        if not has_write:
            push_diag("S001", stmt["chain"][0], "Chain must have explicit write() or write3d() target")
            return None

        write_name = stmt["write"]["name"] if stmt.get("write") else None
        write3d_target = None
        if stmt.get("write3d"):
            w3 = stmt["write3d"]
            tex3d = w3.get("tex3d")
            geo = w3.get("geo")
            write3d_target = {
                "tex3d": {
                    "kind": "vol",
                    "name": (tex3d.get("name") if isinstance(tex3d, dict) else tex3d),
                },
                "geo": {
                    "kind": "geo",
                    "name": (geo.get("name") if isinstance(geo, dict) else geo),
                },
            }
        states = []

        def process_chain(calls, input_, options=None):
            options = options or {}
            allow_starterless = options.get("allowStarterless") is True
            current = input_
            for original in calls:
                ot = original.get("type") if isinstance(original, dict) else None

                if ot == "Read":
                    if current is not None:
                        push_diag(
                            "S001",
                            original,
                            "read() is a starter node and cannot be chained inline. "
                            "Use standalone read() to start a new chain.",
                        )
                        continue
                    surface = _to_surface(original.get("surface"))
                    if not surface:
                        push_diag("S001", original, "read() requires a valid surface reference")
                        continue
                    idx = temp_index[0]
                    temp_index[0] += 1
                    step_args = {"tex": surface}
                    if original.get("_skip") is True:
                        step_args["_skip"] = True
                    step = {"op": "_read", "args": step_args, "from": None, "temp": idx, "builtin": True}
                    if original.get("leadingComments"):
                        step["leadingComments"] = original["leadingComments"]
                    chain.append(step)
                    current = idx
                    continue

                if ot == "Read3D" and original.get("geo"):
                    if current is not None:
                        push_diag(
                            "S001",
                            original,
                            "read3d() is a starter node and cannot be chained inline. "
                            "Use standalone read3d() to start a new chain.",
                        )
                        continue
                    tex3d_node = original.get("tex3d")
                    tex3d = None
                    if tex3d_node and tex3d_node.get("name"):
                        tex3d = {
                            "kind": "vol" if tex3d_node.get("type") == "VolRef" else "tex3d",
                            "name": tex3d_node.get("name"),
                        }
                    geo_node = original.get("geo")
                    geo = None
                    if geo_node and geo_node.get("name"):
                        geo = {"kind": "geo", "name": geo_node.get("name")}
                    if not tex3d or not geo:
                        push_diag("S001", original, "read3d() as starter requires tex3d and geo references")
                        continue
                    idx = temp_index[0]
                    temp_index[0] += 1
                    step_args = {"tex3d": tex3d, "geo": geo}
                    if original.get("_skip") is True:
                        step_args["_skip"] = True
                    step = {"op": "_read3d", "args": step_args, "from": None, "temp": idx, "builtin": True}
                    if original.get("leadingComments"):
                        step["leadingComments"] = original["leadingComments"]
                    chain.append(step)
                    current = idx
                    continue

                if ot == "Write":
                    surface = _to_surface(original.get("surface"))
                    if not surface:
                        push_diag("S001", original, "write() requires a valid surface reference")
                        continue
                    if current is None:
                        push_diag("S005", original, "write() requires an input - cannot be first in chain")
                        continue
                    idx = temp_index[0]
                    temp_index[0] += 1
                    step = {"op": "_write", "args": {"tex": surface}, "from": current, "temp": idx, "builtin": True}
                    if original.get("leadingComments"):
                        step["leadingComments"] = original["leadingComments"]
                    chain.append(step)
                    current = idx
                    continue

                if ot == "Write3D":
                    tex3d_node = original.get("tex3d")
                    tex3d = None
                    if tex3d_node and tex3d_node.get("name"):
                        tex3d = {
                            "kind": "vol" if tex3d_node.get("type") == "VolRef" else "tex3d",
                            "name": tex3d_node.get("name"),
                        }
                    geo_node = original.get("geo")
                    geo = None
                    if geo_node and geo_node.get("name"):
                        geo = {"kind": "geo", "name": geo_node.get("name")}
                    if not tex3d or not geo:
                        push_diag("S001", original, "write3d() requires tex3d and geo references")
                        continue
                    if current is None:
                        push_diag("S005", original, "write3d() requires an input - cannot be first in chain")
                        continue
                    idx = temp_index[0]
                    temp_index[0] += 1
                    step = {"op": "_write3d", "args": {"tex3d": tex3d, "geo": geo}, "from": current, "temp": idx, "builtin": True}
                    if original.get("leadingComments"):
                        step["leadingComments"] = original["leadingComments"]
                    chain.append(step)
                    current = idx
                    continue

                if ot == "Subchain":
                    if current is None:
                        push_diag("S005", original, "subchain() requires an input - cannot be first in chain")
                        continue
                    begin_idx = temp_index[0]
                    temp_index[0] += 1
                    begin_step = {
                        "op": "_subchain_begin",
                        "args": {"name": original.get("name") or None, "id": original.get("id") or None},
                        "from": current,
                        "temp": begin_idx,
                        "builtin": True,
                    }
                    if original.get("leadingComments"):
                        begin_step["leadingComments"] = original["leadingComments"]
                    chain.append(begin_step)
                    current = begin_idx

                    current = process_chain(original.get("body") or [], current)

                    end_idx = temp_index[0]
                    temp_index[0] += 1
                    end_step = {
                        "op": "_subchain_end",
                        "args": {"name": original.get("name") or None, "id": original.get("id") or None},
                        "from": current,
                        "temp": end_idx,
                        "builtin": True,
                    }
                    chain.append(end_step)
                    current = end_idx
                    continue

                call = resolve_call(dict(original))
                effective_namespace = (
                    call.get("namespace") if call.get("namespace") else {"searchOrder": program_search_order}
                )
                op_name = None
                spec = None

                candidate_names = []
                if call.get("namespace") and call["namespace"].get("resolved"):
                    candidate_names.append("%s.%s" % (call["namespace"]["resolved"], call.get("name")))
                search_order = effective_namespace.get("searchOrder")
                if isinstance(search_order, list):
                    for ns in search_order:
                        candidate_names.append("%s.%s" % (ns, call.get("name")))
                for candidate in candidate_names:
                    if candidate and candidate in ops:
                        op_name = candidate
                        spec = ops[candidate]
                        break
                if not spec:
                    push_diag("S001", original, "Unknown effect: '%s'" % call.get("name"))
                    continue

                effect_alias_warning = _ops_mod.check_effect_alias(op_name)
                if effect_alias_warning:
                    push_diag("S008", original, effect_alias_warning)

                if op_name == "prev":
                    idx = temp_index[0]
                    temp_index[0] += 1
                    args = {"tex": {"kind": "output", "name": write_name}}
                    namespace_snapshot = build_namespace_snapshot(call.get("namespace"))
                    step = {"op": op_name, "args": args, "from": current, "temp": idx}
                    if namespace_snapshot:
                        step["namespace"] = namespace_snapshot
                    if original.get("leadingComments"):
                        step["leadingComments"] = original["leadingComments"]
                    chain.append(step)
                    current = idx
                    continue

                is_starter = _ops_mod.is_starter_op(op_name)
                starterless_root = current is None
                allow_passthrough_root = allow_starterless and op_name in _SURFACE_PASSTHROUGH_CALLS
                if starterless_root and not is_starter and not allow_passthrough_root:
                    push_diag("S005", original)
                    continue
                starter_has_input = bool(is_starter and current is not None)
                from_input = None if starter_has_input else current
                if starter_has_input:
                    push_diag("S005", original)

                args = {}
                arg_sources = [None]  # boxed: lazily-created dict
                kw = call.get("kwargs")
                if kw:
                    alias_warnings = _ops_mod.resolve_param_aliases(op_name, kw)
                    for w in alias_warnings:
                        push_diag("S007", call, w)
                seen = set()
                spec_args = spec.get("args") or []
                _resolve_args(
                    spec, spec_args, kw, call, original, op_name, args, arg_sources, seen,
                    process_chain, push_diag, resolve_enum, substitute, get_starter_info,
                    symbols,
                )

                if kw and "_skip" in kw:
                    skip_node = kw["_skip"]
                    if skip_node and skip_node.get("type") == "Boolean":
                        args["_skip"] = skip_node.get("value")
                    else:
                        args["_skip"] = False
                    seen.add("_skip")

                if kw:
                    for key in list(kw.keys()):
                        if key not in seen:
                            push_diag("S001", kw[key], "Unknown argument '%s' for %s()" % (key, call.get("name")))

                # No validator hooks are registered in the reference compile()
                # path (registerValidatorHook is unused by the catalog), so the
                # hook branch is intentionally omitted.

                idx = temp_index[0]
                temp_index[0] += 1
                namespace_snapshot = build_namespace_snapshot(call.get("namespace"))
                step = {"op": op_name, "args": args, "from": from_input, "temp": idx}
                if namespace_snapshot:
                    step["namespace"] = namespace_snapshot
                if original.get("leadingComments"):
                    step["leadingComments"] = original["leadingComments"]
                if original.get("kwargs") and len(original["kwargs"]) > 0:
                    step["rawKwargs"] = original["kwargs"]
                if arg_sources[0]:
                    step["argSources"] = arg_sources[0]
                chain.append(step)
                current = idx
            return current

        final_index = process_chain(stmt["chain"], None)
        write_surf = None
        if stmt.get("write"):
            write_surf = {"kind": "output", "name": stmt["write"]["name"]}
        plan = {
            "chain": chain,
            "write": write_surf,
            "write3d": write3d_target,
            "final": final_index,
            "states": states,
        }
        if stmt.get("leadingComments"):
            plan["leadingComments"] = stmt["leadingComments"]
        return plan

    def compile_block(body):
        result = []
        for s in body or []:
            compiled = compile_stmt(s)
            if compiled:
                result.append(compiled)
        return result

    def compile_stmt(stmt):
        t = stmt.get("type")
        if t == "IfStmt":
            cond = eval_condition(stmt["condition"])
            then_branch = compile_block(stmt.get("then"))
            elif_ = []
            for e in stmt.get("elif") or []:
                elif_.append({"cond": eval_condition(e["condition"]), "then": compile_block(e.get("then"))})
            else_branch = compile_block(stmt.get("else"))
            return {"type": "Branch", "cond": cond, "then": then_branch, "elif": elif_, "else": else_branch}
        if t == "Break":
            return {"type": "Break"}
        if t == "Continue":
            return {"type": "Continue"}
        if t == "Return":
            node = {"type": "Return"}
            if stmt.get("value"):
                node["value"] = eval_expr(stmt["value"])
            return node
        return compile_chain_statement(stmt)

    for stmt in ast.get("plans") or []:
        compiled = compile_stmt(stmt)
        if compiled:
            plans.append(compiled)

    vars_ = ast.get("vars") or []
    search_namespaces = program_search_order or []

    result = {
        "plans": plans,
        "diagnostics": diagnostics_list,
        "render": render,
        "vars": vars_,
        "searchNamespaces": search_namespaces,
    }
    if ast.get("trailingComments"):
        result["trailingComments"] = ast["trailingComments"]
    return result


def _js_string(value):
    """JS ``String(x)`` for the scalar shapes ``extract_identifier_name`` sees."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# The per-argument resolution loop is large; kept as a module-level helper that
# closes over the validator's helpers via explicit parameters so the main
# validate() body stays readable. It is a 1:1 translation of the reference
# ``for (let i = 0; i < specArgs.length; i++)`` block.
def _resolve_args(
    spec, spec_args, kw, call, original, op_name, args, arg_sources, seen,
    process_chain, push_diag, resolve_enum, substitute, get_starter_info, symbols,
):
    def call_to_surface(node):
        if not node or not isinstance(node, dict):
            return None
        if node.get("type") == "Chain" and isinstance(node.get("chain"), list) and len(node["chain"]) == 1:
            return call_to_surface(node["chain"][0])
        if node.get("type") != "Call" or node.get("name") not in _SURFACE_PASSTHROUGH_CALLS:
            return None
        target = None
        if isinstance(node.get("args"), list) and len(node["args"]):
            target = node["args"][0]
        if not target and isinstance(node.get("kwargs"), dict):
            target = node["kwargs"].get("tex")
        if not target:
            return None
        return _to_surface(target)

    i = 0
    n = len(spec_args)
    while i < n:
        def_ = spec_args[i]
        if kw and kw.get(def_["name"], _UNDEF) is not _UNDEF:
            node = kw[def_["name"]]
        else:
            call_args = call.get("args") or []
            node = call_args[i] if i < len(call_args) else _UNDEF
        node = substitute(node) if node is not _UNDEF else _UNDEF
        if node is _UNDEF:
            node = None
        arg_key = def_["name"]

        def_type = def_.get("type")
        default = def_.get("default")

        # Positional Color spread into r/g/b (only when no kwargs).
        if (
            not kw
            and node
            and node.get("type") == "Color"
            and def_type != "color"
            and def_["name"] == "r"
            and i + 1 < n and spec_args[i + 1].get("name") == "g"
            and i + 2 < n and spec_args[i + 2].get("name") == "b"
        ):
            r, g, b = node["value"][0], node["value"][1], node["value"][2]
            args[arg_key] = r
            args[spec_args[i + 1]["name"]] = g
            args[spec_args[i + 2]["name"]] = b
            i += 3
            continue

        if kw and kw.get(def_["name"], _UNDEF) is not _UNDEF:
            seen.add(def_["name"])

        # Array literal -> numeric array (additive input form).
        if node and node.get("type") == "ArrayLiteral":
            value = []
            for el in node["elements"]:
                if el.get("type") == "Number":
                    value.append(el["value"])
                else:
                    push_diag("S002", el, "Array element must be a number for '%s' in %s()" % (def_["name"], call.get("name")))
                    value.append(0)
            args[arg_key] = value
            if arg_sources[0] is None:
                arg_sources[0] = {}
            arg_sources[0][arg_key] = "array"
            i += 1
            continue

        if def_type == "surface":
            _resolve_surface(def_, node, args, arg_key, call, original, push_diag, process_chain, get_starter_info, symbols, call_to_surface)
        elif def_type == "color":
            _resolve_color(def_, node, args, arg_key, call, push_diag)
        elif def_type == "vec3":
            _resolve_vec3(def_, node, args, arg_key, call, push_diag)
        elif def_type == "vec4":
            _resolve_vec4(def_, node, args, arg_key, call, push_diag)
        elif def_type == "boolean":
            _resolve_boolean(def_, node, args, arg_key, call, push_diag)
        elif def_type == "member":
            _resolve_member(def_, node, args, arg_key, call, push_diag, resolve_enum)
        elif def_type == "volume":
            _resolve_volume(def_, node, args, arg_key, push_diag)
        elif def_type == "geometry":
            _resolve_geometry(def_, node, args, arg_key, push_diag)
        elif def_type == "string":
            _resolve_string(def_, node, args, arg_key, op_name, original, push_diag)
        else:
            _resolve_numeric(spec, def_, node, args, arg_key, call, push_diag, resolve_enum)
        i += 1


# --- per-type argument resolvers (translations of validator.js branches) ------

def _resolve_surface(def_, node, args, arg_key, call, original, push_diag, process_chain, get_starter_info, symbols, call_to_surface):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for surface parameter '%s'" % def_["name"])
        args[arg_key] = _to_surface({"type": "Ident", "name": default}) if default else None
        return
    surf = None
    invalid_starter_chain = False
    starter = get_starter_info(node) if node else None
    if node and node.get("type") == "Read" and node.get("surface"):
        surf = _to_surface(node["surface"])
    inline_surface = surf or call_to_surface(node)
    if inline_surface:
        surf = inline_surface
    elif node and node.get("type") == "Chain":
        idx = process_chain(node["chain"], None, {"allowStarterless": True})
        if idx is not None:
            surf = {"kind": "temp", "index": idx}
    elif node and node.get("type") == "Call":
        idx = process_chain([node], None, {"allowStarterless": True})
        if idx is not None:
            surf = {"kind": "temp", "index": idx}
    elif starter:
        push_diag("S005", starter["call"])
        invalid_starter_chain = True
    else:
        surf = _to_surface(node)
    if not surf:
        if invalid_starter_chain:
            args[arg_key] = surf
            return
        if not default:
            if not node:
                push_diag("S001", call, "Missing required surface argument '%s' for %s()" % (def_["name"], call.get("name")))
            elif node.get("type") == "Ident" and node.get("name") not in symbols:
                push_diag("S003", node, "Undefined variable '%s' for '%s' in %s()" % (node.get("name"), def_["name"], call.get("name")))
            else:
                node_name = node.get("name") or (".".join(node["path"]) if node.get("path") else None) or node.get("value") or node.get("type") or "invalid"
                push_diag("S001", node, "Invalid surface reference '%s' for '%s' in %s()" % (node_name, def_["name"], call.get("name")))
        if default:
            surf = _to_surface({"type": "Ident", "name": default}) or {"kind": "pipeline", "name": default}
    args[arg_key] = surf


def _resolve_color(def_, node, args, arg_key, call, push_diag):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for color parameter '%s'" % def_["name"])
        args[arg_key] = default
        return
    if node and node.get("type") == "Color":
        value = node.get("hex") if node.get("hex") else node.get("value")
    else:
        if node and node.get("type") and node.get("type") != "Ident":
            push_diag("S002", node, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
        value = default
    args[arg_key] = value


def _resolve_vec3(def_, node, args, arg_key, call, push_diag):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for vec3 parameter '%s'" % def_["name"])
        args[arg_key] = list(default) if default else [0, 0, 0]
        return
    if node and node.get("type") == "Call" and node.get("name") == "vec3" and node.get("args") and len(node["args"]) == 3:
        value = []
        for arg in node["args"]:
            if arg.get("type") == "Number":
                value.append(arg["value"])
            else:
                push_diag("S002", arg, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
                value.append(0)
    elif node and node.get("type") == "Color":
        value = node["value"][0:3]
    else:
        if node and node.get("type") and node.get("type") != "Ident":
            push_diag("S002", node, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
        value = list(default) if default else [0, 0, 0]
    args[arg_key] = value


def _resolve_vec4(def_, node, args, arg_key, call, push_diag):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for vec4 parameter '%s'" % def_["name"])
        args[arg_key] = list(default) if default else [0, 0, 0, 1]
        return
    if node and node.get("type") == "Call" and node.get("name") == "vec4" and node.get("args") and len(node["args"]) == 4:
        value = []
        for arg in node["args"]:
            if arg.get("type") == "Number":
                value.append(arg["value"])
            else:
                push_diag("S002", arg, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
                value.append(0)
    elif node and node.get("type") == "Color":
        value = list(node["value"])
    else:
        if node and node.get("type") and node.get("type") != "Ident":
            push_diag("S002", node, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
        value = list(default) if default else [0, 0, 0, 1]
    args[arg_key] = value


def _resolve_boolean(def_, node, args, arg_key, call, push_diag):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for boolean parameter '%s'" % def_["name"])
        args[arg_key] = bool(default) if default is not None else False
        return
    if node and node.get("type") == "Boolean":
        value = bool(node.get("value"))
    elif node and node.get("type") == "Number":
        value = node["value"] != 0
    elif node and node.get("type") == "Func":
        value = {"fn": {"_func_src": node.get("src")}}
    elif node and node.get("type") == "Ident" and node.get("name") in _STATE_VALUES:
        value = {"fn": {"_state": node["name"]}}
    else:
        if node and node.get("type") == "Ident" and node.get("name") not in _STATE_VALUES:
            push_diag("S003", node)
        elif node and node.get("type") and node.get("type") != "Ident":
            push_diag("S002", node, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
        value = bool(default) if default is not None else False
    args[arg_key] = value


def _resolve_member(def_, node, args, arg_key, call, push_diag, resolve_enum):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for member/enum parameter '%s'" % def_["name"])
        args[arg_key] = default
        return
    prefix = normalize_member_path(def_.get("enumPath") or def_.get("enum"))
    path = None
    if node and node.get("type") == "Member":
        path = normalize_member_path(node.get("path"))
    elif node and node.get("type") in ("Number", "Boolean"):
        args[arg_key] = (1 if node["value"] else 0) if node.get("type") == "Boolean" else node["value"]
        return
    elif node and node.get("type") == "Ident" and node.get("name") in _STATE_VALUES:
        args[arg_key] = {"fn": {"_state": node["name"]}}
        return
    elif node and node.get("type") == "Ident":
        path = [node["name"]]
    if not path:
        path = normalize_member_path(default)
    resolved = resolve_enum(path) if path else _UNDEF
    resolved = _coerce_enum_scalar(resolved)
    if not _is_number(resolved):
        path = apply_enum_prefix(path or [], prefix)
        if prefix and path and not path_starts_with(path, prefix):
            push_diag("S001", node or call, "Invalid enum value for '%s': expected path starting with '%s'" % (def_["name"], ".".join(prefix)))
            path = list(prefix)
        resolved = resolve_enum(path) if path else _UNDEF
        resolved = _coerce_enum_scalar(resolved)
    if not _is_number(resolved):
        fallback = normalize_member_path(default)
        fallback_value = resolve_enum(fallback) if fallback else _UNDEF
        fallback_value = _coerce_enum_scalar(fallback_value)
        if _is_number(fallback_value):
            resolved = fallback_value
        else:
            resolved = 0
    args[arg_key] = resolved
    if node and node.get("type") == "Member" and path:
        node["path"] = list(path)


def _coerce_enum_scalar(resolved):
    if isinstance(resolved, dict) and resolved.get("type") == "Number":
        return resolved.get("value")
    if isinstance(resolved, dict) and resolved.get("type") == "Boolean":
        return 1 if resolved.get("value") else 0
    return resolved


def _resolve_volume(def_, node, args, arg_key, push_diag):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for volume parameter '%s'" % def_["name"])
        args[arg_key] = {"kind": "vol", "name": default} if default else None
        return
    value = None
    if node and node.get("type") == "Read3D" and node.get("tex3d") and not node.get("geo"):
        vol_name = node["tex3d"]["name"]
        if _VOL_RE.match(vol_name):
            value = {"kind": "vol", "name": vol_name}
        else:
            push_diag("S001", node, "Invalid volume reference '%s' in read3d() for '%s' - expected vol0-vol7" % (vol_name, def_["name"]))
            value = {"kind": "vol", "name": default} if default else None
    elif node and node.get("type") == "VolRef":
        value = {"kind": "vol", "name": node["name"]}
    elif node and node.get("type") == "Ident":
        if node["name"] == "none":
            value = {"kind": "vol", "name": "none"}
        elif _VOL_RE.match(node["name"]):
            value = {"kind": "vol", "name": node["name"]}
        else:
            push_diag("S001", node, "Invalid volume reference '%s' for '%s' - expected vol0-vol7 or none" % (node["name"], def_["name"]))
            value = {"kind": "vol", "name": default} if default else None
    elif not node and default:
        value = {"kind": "vol", "name": default}
    args[arg_key] = value


def _resolve_geometry(def_, node, args, arg_key, push_diag):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for geometry parameter '%s'" % def_["name"])
        args[arg_key] = {"kind": "geo", "name": default} if default else None
        return
    value = None
    if node and node.get("type") == "Read3D" and node.get("tex3d") and not node.get("geo"):
        geo_name = node["tex3d"]["name"]
        if _GEO_RE.match(geo_name):
            value = {"kind": "geo", "name": geo_name}
        else:
            push_diag("S001", node, "Invalid geometry reference '%s' in read3d() for '%s' - expected geo0-geo7" % (geo_name, def_["name"]))
            value = {"kind": "geo", "name": default} if default else None
    elif node and node.get("type") == "GeoRef":
        value = {"kind": "geo", "name": node["name"]}
    elif node and node.get("type") == "Ident":
        if node["name"] == "none":
            value = {"kind": "geo", "name": "none"}
        elif _GEO_RE.match(node["name"]):
            value = {"kind": "geo", "name": node["name"]}
        else:
            push_diag("S001", node, "Invalid geometry reference '%s' for '%s' - expected geo0-geo7 or none" % (node["name"], def_["name"]))
            value = {"kind": "geo", "name": default} if default else None
    elif not node and default:
        value = {"kind": "geo", "name": default}
    args[arg_key] = value


def _resolve_string(def_, node, args, arg_key, op_name, original, push_diag):
    default = def_.get("default")
    func_name = op_name.split(".")[-1] if "." in op_name else op_name
    allowlist_key = "%s.%s" % (func_name, def_["name"])
    if allowlist_key not in _ALLOWED_STRING_PARAMS:
        push_diag(
            "S001",
            node or original,
            "String parameter '%s' on effect '%s' is NOT in the allowed string params list. "
            "String params are strictly controlled - use enums or choices instead." % (def_["name"], func_name),
        )
        args[arg_key] = default
        return
    if node and node.get("type") == "String":
        value = node["value"]
    elif node and node.get("type") == "Ident" and def_.get("choices"):
        choices = def_["choices"]
        if node["name"] in choices:
            value = choices[node["name"]]
        else:
            push_diag("S001", node, "Invalid choice '%s' for string parameter '%s'" % (node["name"], def_["name"]))
            value = default
    elif node:
        push_diag("S001", node, "String parameter '%s' requires a quoted string literal, got %s" % (def_["name"], node.get("type")))
        value = default
    else:
        value = default
    args[arg_key] = value


def _resolve_numeric(spec, def_, node, args, arg_key, call, push_diag, resolve_enum):
    default = def_.get("default")
    if node and node.get("type") == "String":
        push_diag("S001", node, "String literal not allowed for numeric parameter '%s' - strings are only valid for type: \"string\" parameters" % def_["name"])
        args[arg_key] = default
        return
    value = _UNDEF
    if node and node.get("type") in ("Number", "Boolean"):
        raw = (1 if node["value"] else 0) if node.get("type") == "Boolean" else node["value"]
        clamped = clamp(raw, def_.get("min"), def_.get("max"))
        if clamped != raw:
            push_diag("S002", node, "Argument out of range for '%s' in %s() (got %s, clamped to %s)" % (def_["name"], call.get("name"), _js_string(raw), _js_string(clamped)))
        value = clamped
        if node.get("_varRef"):
            value = {"_varRef": node["_varRef"], "value": value}
    elif node and node.get("type") == "Func":
        value = {"fn": {"_func_src": node.get("src")}, "min": def_.get("min"), "max": def_.get("max")}
    elif node and node.get("type") == "Oscillator":
        value = _resolve_oscillator(node, resolve_enum)
    elif node and node.get("type") == "Midi":
        value = _resolve_midi(node, resolve_enum)
    elif node and node.get("type") == "Audio":
        value = _resolve_audio(node, resolve_enum)
    elif node and node.get("type") == "Member":
        cur = resolve_enum(node["path"])
        if _is_number(cur):
            value = clamp(cur, def_.get("min"), def_.get("max"))
            if value != cur:
                push_diag("S002", node, "Argument out of range for '%s' in %s() (got %s, clamped to %s)" % (def_["name"], call.get("name"), _js_string(cur), _js_string(value)))
        elif isinstance(cur, bool):
            num = 1 if cur else 0
            value = clamp(num, def_.get("min"), def_.get("max"))
            if value != num:
                push_diag("S002", node, "Argument out of range for '%s' in %s() (got %s, clamped to %s)" % (def_["name"], call.get("name"), _js_string(num), _js_string(value)))
        else:
            push_diag("S001", node, "Cannot resolve enum value for '%s': '%s'" % (def_["name"], (".".join(node["path"]) if node.get("path") else (node.get("name") or "unknown"))))
            value = default
    elif node and node.get("type") == "Ident" and node.get("name") in _STATE_VALUES:
        value = {"fn": {"_state": node["name"]}, "min": def_.get("min"), "max": def_.get("max")}
    elif node and node.get("type") == "Ident" and def_.get("enum"):
        prefix = normalize_member_path(def_["enum"])
        path = (list(prefix) + [node["name"]]) if prefix else [node["name"]]
        resolved = resolve_enum(path)
        if _is_number(resolved):
            value = clamp(resolved, def_.get("min"), def_.get("max"))
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            value = clamp(resolved["value"], def_.get("min"), def_.get("max"))
        else:
            push_diag("S003", node)
            value = default
    elif node and node.get("type") == "Ident" and def_.get("choices"):
        choice_val = def_["choices"].get(node["name"])
        if _is_number(choice_val):
            value = clamp(choice_val, def_.get("min"), def_.get("max"))
        else:
            push_diag("S003", node)
            value = default
    else:
        if node and node.get("type") == "Ident" and node.get("name") not in _STATE_VALUES:
            push_diag("S003", node)
        elif node and node.get("type") and node.get("type") != "Ident":
            push_diag("S002", node, "Argument out of range for '%s' in %s()" % (def_["name"], call.get("name")))
        if def_.get("defaultFrom"):
            ref = next((d for d in (spec.get("args") or []) if d.get("name") == def_["defaultFrom"]), None)
            ref_key = ref["name"] if ref else def_["defaultFrom"]
            if ref_key in args:
                value = args[ref_key]
            else:
                value = default
        else:
            value = default
    args[arg_key] = None if value is _UNDEF else value


def _osc_resolve_param(param, resolve_enum):
    if not param:
        return _UNDEF
    t = param.get("type")
    if t == "Number":
        return param["value"]
    if t == "Boolean":
        return 1 if param["value"] else 0
    if t == "Member":
        r = resolve_enum(param["path"])
        if _is_number(r):
            return r
        if isinstance(r, dict) and r.get("type") == "Number":
            return r["value"]
    return _UNDEF


def _clamp01(v):
    if isinstance(v, float) and math.isnan(v):
        return v
    return max(0, min(1, v))


def _qq(v, fallback):
    """JS ``x ?? fallback`` where x is _UNDEF/None -> fallback."""
    return fallback if (v is _UNDEF or v is None) else v


def _resolve_oscillator(node, resolve_enum):
    osc_type_node = node.get("oscType")
    osc_type_value = 0
    if osc_type_node and osc_type_node.get("type") == "Member":
        resolved = resolve_enum(osc_type_node["path"])
        if _is_number(resolved):
            osc_type_value = resolved
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            osc_type_value = resolved["value"]
    elif osc_type_node and osc_type_node.get("type") == "Ident":
        resolved = resolve_enum(["oscKind", osc_type_node["name"]])
        if _is_number(resolved):
            osc_type_value = resolved
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            osc_type_value = resolved["value"]
    value = {
        "type": "Oscillator",
        "oscType": osc_type_value,
        "min": _clamp01(_qq(_osc_resolve_param(node.get("min"), resolve_enum), 0)),
        "max": _clamp01(_qq(_osc_resolve_param(node.get("max"), resolve_enum), 1)),
        "speed": _qq(_osc_resolve_param(node.get("speed"), resolve_enum), 1),
        "offset": _qq(_osc_resolve_param(node.get("offset"), resolve_enum), 0),
        "seed": _qq(_osc_resolve_param(node.get("seed"), resolve_enum), 1),
        "_ast": node,
    }
    if node.get("_varRef"):
        value["_varRef"] = node["_varRef"]
    return value


def _resolve_midi(node, resolve_enum):
    mode_node = node.get("mode")
    mode_value = 4
    if mode_node and mode_node.get("type") == "Member":
        resolved = resolve_enum(mode_node["path"])
        if _is_number(resolved):
            mode_value = resolved
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            mode_value = resolved["value"]
    elif mode_node and mode_node.get("type") == "Ident":
        resolved = resolve_enum(["midiMode", mode_node["name"]])
        if _is_number(resolved):
            mode_value = resolved
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            mode_value = resolved["value"]
    elif (
        mode_node
        and mode_node.get("type") == "Number"
        and _is_number(mode_node.get("value"))
        and (
            isinstance(mode_node["value"], int)
            or (
                math.isfinite(mode_node["value"])
                and mode_node["value"].is_integer()
            )
        )
        and 0 <= mode_node["value"] <= 4
    ):
        mode_value = mode_node["value"]
    value = {
        "type": "Midi",
        "channel": _qq(_osc_resolve_param(node.get("channel"), resolve_enum), 1),
        "mode": mode_value,
        "min": _clamp01(_qq(_osc_resolve_param(node.get("min"), resolve_enum), 0)),
        "max": _clamp01(_qq(_osc_resolve_param(node.get("max"), resolve_enum), 1)),
        "sensitivity": _qq(_osc_resolve_param(node.get("sensitivity"), resolve_enum), 1),
        "_ast": node,
    }
    for param_name in ("name", "id"):
        param = node.get(param_name)
        if param is None:
            continue
        allowlist_key = "midi.%s" % param_name
        if allowlist_key not in _ALLOWED_STRING_PARAMS:
            continue
        if param.get("type") == "String" and len(param.get("value", "")) > 0:
            value[param_name] = decode_json_string_literal_content(param["value"])
    if node.get("_varRef"):
        value["_varRef"] = node["_varRef"]
    return value


def _resolve_audio(node, resolve_enum):
    band_node = node.get("band")
    band_value = 0
    if band_node and band_node.get("type") == "Member":
        resolved = resolve_enum(band_node["path"])
        if _is_number(resolved):
            band_value = resolved
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            band_value = resolved["value"]
    elif band_node and band_node.get("type") == "Ident":
        resolved = resolve_enum(["audioBand", band_node["name"]])
        if _is_number(resolved):
            band_value = resolved
        elif isinstance(resolved, dict) and resolved.get("type") == "Number":
            band_value = resolved["value"]
    value = {
        "type": "Audio",
        "band": band_value,
        "min": _clamp01(_qq(_osc_resolve_param(node.get("min"), resolve_enum), 0)),
        "max": _clamp01(_qq(_osc_resolve_param(node.get("max"), resolve_enum), 1)),
        "_ast": node,
    }
    if node.get("_varRef"):
        value["_varRef"] = node["_varRef"]
    return value
