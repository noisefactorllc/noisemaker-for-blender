"""Recursive-descent parser for the Noisemaker Polymorphic DSL.

Faithful Python port of the reference parser (shaders/src/lang/parser.js). Consumes the
token list produced by the stage-1 lexer (``noisemaker_blender.compiler.lexer.lex``) and
produces an AST whose node shapes are byte-for-byte equivalent to the reference's ``parse()``
output (verified structurally against golden ASTs over the parity corpus).

Pure stdlib, fully self-contained: this runs inside Blender's bundled Python, so there are no
third-party imports and no dependency on the reference repo. The two symbols the reference
parser imports from ``runtime/tags.js`` (``isValidNamespace`` / ``VALID_NAMESPACES``) are
inlined below as the static set of built-in namespace IDs — the parser never registers or
unregisters namespaces at runtime, so a frozen list reproduces its behavior exactly.

Grammar (EBNF), mirroring the reference:

    Program        ::= SearchDirective? Statement* RenderDirective?
    SearchDirective::= 'search' Ident (',' Ident)*
    Statement      ::= VarAssign | ChainStmt | IfStmt | Break | Continue | Return
    RenderDirective::= 'render' '(' OutputRef ')'
    Block          ::= '{' Statement* '}'
    IfStmt         ::= 'if' '(' Expr ')' Block ('elif' '(' Expr ')' Block)* ('else' Block)?
    Break          ::= 'break'
    Continue       ::= 'continue'
    Return         ::= 'return' Expr?
    VarAssign      ::= 'let' Ident '=' Expr
    ChainStmt      ::= Chain
    Chain          ::= ChainElement ('.' ChainElement)*
    ChainElement   ::= Call | WriteNode | Write3DNode
    Expr           ::= Chain | NumberExpr | String | Boolean | Color | Ident | Member
                       | OutputRef | SourceRef | Func | '(' Expr ')'
    Call           ::= Ident '(' ArgList? ')'
    NumberExpr     ::= Number | 'Math.PI' | '(' NumberExpr ')'
                       | NumberExpr ( '+' | '-' | '*' | '/' ) NumberExpr

The AST node contract (what later compiler stages can rely on) is documented inline at each
production. ``parse(tokens)`` is the primary entry point; ``parse_source(src)`` lexes then parses.
"""

import math

from .lexer import lex


class SyntaxError_(SyntaxError):
    """Raised on malformed source (mirrors the reference's thrown ``SyntaxError``).

    Named with a trailing underscore so it does not shadow the builtin ``SyntaxError`` at the
    use sites below, while still subclassing it so ``except SyntaxError`` also catches it.
    """


# Built-in namespace IDs accepted by the `search` directive. Mirrors the seed set in
# runtime/tags.js (_builtinDescriptors). The reference's isValidNamespace() also accepts
# namespaces registered at runtime via registerNamespace(), but the parser stage never
# registers any, so this static frozenset reproduces parse-time validation exactly.
VALID_NAMESPACES = (
    "io",
    "classicNoisedeck",
    "synth",
    "mixer",
    "filter",
    "render",
    "points",
    "synth3d",
    "filter3d",
    "user",
)
_VALID_NAMESPACES_SET = frozenset(VALID_NAMESPACES)


def _is_valid_namespace(namespace_id):
    return namespace_id in _VALID_NAMESPACES_SET


def _make_number(value):
    """Produce a Number node value matching JS numeric semantics.

    JS has a single Number type; ``JSON.stringify`` of an integral float (e.g. ``30.0``)
    emits ``30``. We mirror that by storing integral values as Python ``int`` so the
    serialized/structural form matches the golden, and non-integral values as ``float``.
    """
    if isinstance(value, float) and value.is_integer() and not math.isinf(value):
        return int(value)
    return value


def _parse_js_number(lexeme):
    """Parse a numeric lexeme the way JS ``parseFloat`` would, returning int-or-float."""
    return _make_number(float(lexeme))


def parse(tokens):
    """Parse a token stream into an AST.

    :param tokens: token list from :func:`noisemaker_blender.compiler.lexer.lex`
    :returns: the Program AST (a nested dict / list structure)
    :raises SyntaxError_: on malformed input (same cases as the reference parser)
    """
    state = {"current": 0}

    # Track the search order for the program (set by search directive - REQUIRED).
    program_search_order = {"value": None}

    # Program namespace starts empty - must be set by search directive.
    program_namespace = {"imports": [], "default": None}

    def peek():
        return tokens[state["current"]]

    def advance():
        tok = tokens[state["current"]]
        state["current"] += 1
        return tok

    def tok_at(idx):
        """Bounds-safe token lookup; returns None past the end (mirrors JS ``tokens[i]``)."""
        if 0 <= idx < len(tokens):
            return tokens[idx]
        return None

    def expect(type_, msg):
        token = peek()
        if token["type"] == type_:
            return advance()
        raise SyntaxError_("%s at line %d col %d" % (msg, token["line"], token["col"]))

    def collect_comments():
        """Collect and consume any pending COMMENT tokens; return list of lexeme strings."""
        comments = []
        while True:
            t = peek()
            if t is not None and t.get("type") == "COMMENT":
                comments.append(advance()["lexeme"])
            else:
                break
        return comments

    expr_start_tokens = frozenset([
        "PLUS", "MINUS", "NUMBER", "HEX", "FUNC", "STRING",
        "IDENT", "OUTPUT_REF", "SOURCE_REF", "VOL_REF", "GEO_REF", "MESH_REF",
        "XYZ_REF", "VEL_REF", "RGBA_REF", "LPAREN", "LBRACKET",
        "TRUE", "FALSE",
    ])

    member_token_types = frozenset([
        "IDENT", "SOURCE_REF", "OUTPUT_REF", "VOL_REF", "GEO_REF", "MESH_REF",
        "XYZ_REF", "VEL_REF", "RGBA_REF",
        "LET", "RENDER", "TRUE", "FALSE", "IF", "ELIF", "ELSE",
        "BREAK", "CONTINUE", "RETURN", "WRITE", "WRITE3D", "SUBCHAIN",
    ])

    # ---- osc()/midi()/audio()/from() invocation transforms ------------------------------

    def transform_osc_invocation(call, name_token):
        """Transform an osc() call into an Oscillator AST node.

        osc(type, min?, max?, speed?, offset?, seed?) — all params except 'type' optional,
        positional or kwargs.
        """
        args = call["args"] if isinstance(call.get("args"), list) else []
        kwargs = call.get("kwargs") or {}

        param_order = ["type", "min", "max", "speed", "offset", "seed"]
        valid_params = set(param_order)
        defaults = {
            "type": {"type": "Member", "path": ["oscKind", "sine"]},
            "min": {"type": "Number", "value": 0},
            "max": {"type": "Number", "value": 1},
            "speed": {"type": "Number", "value": 1},
            "offset": {"type": "Number", "value": 0},
            "seed": {"type": "Number", "value": 1},
        }

        for key in kwargs.keys():
            if key not in valid_params:
                raise SyntaxError_(
                    "osc() unknown parameter '%s' at line %d col %d. Valid: %s"
                    % (key, name_token["line"], name_token["col"], ", ".join(param_order))
                )

        resolved = {}
        for i, param_name in enumerate(param_order):
            if kwargs.get(param_name) is not None:
                resolved[param_name] = kwargs[param_name]
            elif i < len(args):
                resolved[param_name] = args[i]
            elif defaults.get(param_name) is not None:
                resolved[param_name] = defaults[param_name]

        return {
            "type": "Oscillator",
            "oscType": resolved.get("type"),
            "min": resolved.get("min"),
            "max": resolved.get("max"),
            "speed": resolved.get("speed"),
            "offset": resolved.get("offset"),
            "seed": resolved.get("seed"),
            "loc": {"line": name_token["line"], "col": name_token["col"]},
        }

    def transform_midi_invocation(call, name_token):
        """Transform a midi() call into a Midi AST node.

        midi(channel, mode?, min?, max?, sensitivity?) — channel required.
        """
        args = call["args"] if isinstance(call.get("args"), list) else []
        kwargs = call.get("kwargs") or {}

        param_order = ["channel", "mode", "min", "max", "sensitivity"]
        defaults = {
            "mode": {"type": "Member", "path": ["midiMode", "velocity"]},
            "min": {"type": "Number", "value": 0},
            "max": {"type": "Number", "value": 1},
            "sensitivity": {"type": "Number", "value": 1},
        }

        resolved = {}
        for i, param_name in enumerate(param_order):
            if kwargs.get(param_name) is not None:
                resolved[param_name] = kwargs[param_name]
            elif i < len(args):
                resolved[param_name] = args[i]
            elif defaults.get(param_name) is not None:
                resolved[param_name] = defaults[param_name]

        if not resolved.get("channel"):
            raise SyntaxError_(
                "midi() requires 'channel' argument at line %d col %d"
                % (name_token["line"], name_token["col"])
            )

        return {
            "type": "Midi",
            "channel": resolved.get("channel"),
            "mode": resolved.get("mode"),
            "min": resolved.get("min"),
            "max": resolved.get("max"),
            "sensitivity": resolved.get("sensitivity"),
            "loc": {"line": name_token["line"], "col": name_token["col"]},
        }

    def transform_audio_invocation(call, name_token):
        """Transform an audio() call into an Audio AST node.

        audio(band, min?, max?) — band required.
        """
        args = call["args"] if isinstance(call.get("args"), list) else []
        kwargs = call.get("kwargs") or {}

        param_order = ["band", "min", "max"]
        defaults = {
            "min": {"type": "Number", "value": 0},
            "max": {"type": "Number", "value": 1},
        }

        resolved = {}
        for i, param_name in enumerate(param_order):
            if kwargs.get(param_name) is not None:
                resolved[param_name] = kwargs[param_name]
            elif i < len(args):
                resolved[param_name] = args[i]
            elif defaults.get(param_name) is not None:
                resolved[param_name] = defaults[param_name]

        if not resolved.get("band"):
            raise SyntaxError_(
                "audio() requires 'band' argument at line %d col %d"
                % (name_token["line"], name_token["col"])
            )

        return {
            "type": "Audio",
            "band": resolved.get("band"),
            "min": resolved.get("min"),
            "max": resolved.get("max"),
            "loc": {"line": name_token["line"], "col": name_token["col"]},
        }

    def transform_from_invocation(call, name_token):
        def fail(message):
            if (
                name_token is not None
                and isinstance(name_token.get("line"), int)
                and isinstance(name_token.get("col"), int)
            ):
                raise SyntaxError_(
                    "%s at line %d col %d" % (message, name_token["line"], name_token["col"])
                )
            raise SyntaxError_(message)

        if call.get("kwargs") and len(call["kwargs"]):
            fail("'from' does not support named arguments")
        args = call["args"] if isinstance(call.get("args"), list) else []
        if len(args) != 2:
            fail("'from' requires exactly two arguments (namespace, call)")
        namespace_arg, target_arg = args[0], args[1]
        if not namespace_arg or (
            namespace_arg.get("type") != "Ident" and namespace_arg.get("type") != "Member"
        ):
            fail("'from' namespace argument must be an identifier")
        if namespace_arg.get("type") == "Member":
            namespace_name = ".".join(namespace_arg["path"])
        else:
            namespace_name = namespace_arg.get("name")
        if not namespace_name:
            fail("'from' namespace argument must be non-empty")

        target_call = None
        if target_arg and target_arg.get("type") == "Call":
            target_call = target_arg
        elif (
            target_arg
            and target_arg.get("type") == "Chain"
            and isinstance(target_arg.get("chain"), list)
            and len(target_arg["chain"]) == 1
        ):
            head = target_arg["chain"][0]
            if head and head.get("type") == "Call":
                target_call = head
        if not target_call:
            fail("'from' second argument must be a call expression")

        # Shallow-clone the target call, copying its args list (JS: targetCall.args.map(a => a)).
        replacement = dict(target_call)
        if isinstance(target_call.get("args"), list):
            replacement["args"] = list(target_call["args"])
        else:
            replacement["args"] = []
        if target_call.get("kwargs"):
            replacement["kwargs"] = dict(target_call["kwargs"])

        override_namespace = {
            "name": namespace_name,
            "path": [namespace_name],
            "explicit": True,
            "source": "from",
            "resolved": namespace_name,
            "searchOrder": [namespace_name],
            "fromOverride": True,
        }
        replacement["namespace"] = override_namespace
        return replacement

    def has_call_after_dot(index):
        i = index + 1
        t = tok_at(i)
        if t is None or t.get("type") != "DOT":
            return False
        while True:
            t = tok_at(i)
            if t is None or t.get("type") != "DOT":
                break
            seg_token = tok_at(i + 1)
            if seg_token is None or seg_token.get("type") not in member_token_types:
                return False
            i += 2
        t = tok_at(i)
        return t is not None and t.get("type") == "LPAREN"

    def parse_render_directive():
        advance()
        expect("LPAREN", "Expect '('")
        if peek()["type"] != "OUTPUT_REF":
            raise SyntaxError_("Expected output reference in render()")
        out = {"type": "OutputRef", "name": advance()["lexeme"]}
        expect("RPAREN", "Expect ')'")
        return out

    def parse_program():
        plans = []
        variables = []
        render = {"value": None}
        trailing_comments = []

        def append_statement(stmt):
            if not stmt or not isinstance(stmt, dict):
                return
            if stmt.get("type") == "VarAssign":
                variables.append(stmt)
            else:
                plans.append(stmt)

        def consume_render():
            if render["value"]:
                t = peek()
                raise SyntaxError_(
                    "Duplicate render() directive at line %d col %d" % (t["line"], t["col"])
                )
            render["value"] = parse_render_directive()
            while peek()["type"] == "SEMICOLON":
                advance()

        # Token types that can be used as namespace identifiers (keywords like 'render' are
        # valid namespace names in search context).
        namespace_token_types = frozenset([
            "IDENT", "RENDER", "WRITE", "WRITE3D", "TRUE", "FALSE",
            "IF", "ELIF", "ELSE", "BREAK", "CONTINUE", "RETURN",
        ])

        def parse_search_directive():
            if program_search_order["value"] is not None:
                t = peek()
                raise SyntaxError_(
                    "Only one search directive is allowed per program at line %d col %d"
                    % (t["line"], t["col"])
                )
            advance()  # consume 'search'
            namespaces = []

            def validate_namespace(token):
                ns = token["lexeme"]
                if not _is_valid_namespace(ns):
                    raise SyntaxError_(
                        "Invalid namespace '%s' at line %d col %d. Valid namespaces: %s"
                        % (ns, token["line"], token["col"], ", ".join(VALID_NAMESPACES))
                    )

            first_token = peek()
            if first_token["type"] not in namespace_token_types:
                raise SyntaxError_(
                    "Expected namespace identifier after search at line %d col %d"
                    % (first_token["line"], first_token["col"])
                )
            advance()
            validate_namespace(first_token)
            namespaces.append(first_token["lexeme"])
            while peek()["type"] == "COMMA":
                advance()  # consume ','
                ns_token = peek()
                if ns_token["type"] not in namespace_token_types:
                    raise SyntaxError_(
                        "Expected namespace identifier after comma at line %d col %d"
                        % (ns_token["line"], ns_token["col"])
                    )
                advance()
                validate_namespace(ns_token)
                namespaces.append(ns_token["lexeme"])
            program_search_order["value"] = namespaces
            program_namespace["imports"] = [
                {"name": name, "source": "search", "explicit": True} for name in namespaces
            ]
            program_namespace["default"] = {
                "name": namespaces[0], "source": "search", "explicit": True
            }
            while peek()["type"] == "SEMICOLON":
                advance()

        while peek()["type"] != "EOF":
            if peek()["type"] == "SEMICOLON":
                advance()
                continue
            leading_comments = collect_comments()
            if peek()["type"] == "EOF":
                if len(leading_comments) > 0:
                    trailing_comments.extend(leading_comments)
                break
            if peek()["type"] == "SEMICOLON":
                continue
            if peek()["type"] == "SEARCH":
                if len(plans) or len(variables) or render["value"]:
                    t = peek()
                    raise SyntaxError_(
                        "'search' directive must appear before other statements "
                        "at line %d col %d" % (t["line"], t["col"])
                    )
                parse_search_directive()
                continue
            if peek()["type"] == "RENDER":
                consume_render()
                if len(leading_comments) > 0 and render["value"]:
                    render["value"]["leadingComments"] = leading_comments
                trailing = collect_comments()
                if len(trailing) > 0:
                    trailing_comments.extend(trailing)
                break
            stmt = parse_statement()
            if len(leading_comments) > 0 and stmt:
                stmt["leadingComments"] = leading_comments
            append_statement(stmt)
            while peek()["type"] == "SEMICOLON":
                advance()

        expect("EOF", "Expected end of input")
        if not program_search_order["value"] or len(program_search_order["value"]) == 0:
            raise SyntaxError_(
                "Missing required 'search' directive. Every program must start with "
                "'search <namespace>, ...' to specify namespace search order."
            )

        program = {"type": "Program", "plans": plans, "render": render["value"]}
        if len(variables):
            program["vars"] = variables
        if len(trailing_comments):
            program["trailingComments"] = trailing_comments

        search_order = list(program_search_order["value"])
        imports_clone = [dict(entry) for entry in program_namespace["imports"]]
        default_clone = (
            dict(program_namespace["default"]) if program_namespace["default"] else None
        )
        program["namespace"] = {
            "imports": imports_clone,
            "default": default_clone,
            "searchOrder": list(search_order),
        }
        return program

    def parse_block():
        expect("LBRACE", "Expect '{'")
        body = []
        while peek()["type"] != "RBRACE":
            stmt = parse_statement()
            body.append(stmt)
            while peek()["type"] == "SEMICOLON":
                advance()
        expect("RBRACE", "Expect '}'")
        return body

    def parse_statement():
        if peek()["type"] == "SEARCH":
            t = peek()
            raise SyntaxError_(
                "'search' directive is only allowed at the start of the program "
                "at line %d col %d" % (t["line"], t["col"])
            )
        if peek()["type"] == "LET":
            advance()
            name = expect("IDENT", "Expected identifier")["lexeme"]
            expect("EQUAL", "Expect '='")
            if peek()["type"] not in expr_start_tokens:
                t = peek()
                raise SyntaxError_(
                    "Expected expression after '=' at line %d col %d" % (t["line"], t["col"])
                )
            expr = parse_additive()
            return {"type": "VarAssign", "name": name, "expr": expr}

        tt = peek()["type"]
        if tt == "IF":
            advance()
            expect("LPAREN", "Expect '('")
            condition = parse_additive()
            expect("RPAREN", "Expect ')'")
            then = parse_block()
            elif_branches = []
            while peek()["type"] == "ELIF":
                advance()
                expect("LPAREN", "Expect '('")
                ec = parse_additive()
                expect("RPAREN", "Expect ')'")
                body = parse_block()
                elif_branches.append({"condition": ec, "then": body})
            else_branch = None
            if peek()["type"] == "ELSE":
                advance()
                else_branch = parse_block()
            return {
                "type": "IfStmt",
                "condition": condition,
                "then": then,
                "elif": elif_branches,
                "else": else_branch,
            }
        if tt == "BREAK":
            advance()
            return {"type": "Break"}
        if tt == "CONTINUE":
            advance()
            return {"type": "Continue"}
        if tt == "RETURN":
            advance()
            if peek()["type"] in expr_start_tokens:
                value = parse_additive()
                return {"type": "Return", "value": value}
            return {"type": "Return"}

        chain = parse_chain()
        # Extract write/write3d only if the chain TERMINATES with a Write/Write3D node.
        write = None
        write3d = None
        if len(chain) > 0:
            last_node = chain[len(chain) - 1]
            if last_node.get("type") == "Write":
                write = last_node["surface"]
            elif last_node.get("type") == "Write3D":
                write3d = {"tex3d": last_node["tex3d"], "geo": last_node["geo"]}

        return {"chain": chain, "write": write, "write3d": write3d}

    def parse_chain(context="statement"):
        first_call = parse_call()
        calls = [first_call]
        while True:
            saved_pos = state["current"]
            leading_comments = collect_comments()
            if peek()["type"] != "DOT":
                state["current"] = saved_pos
                break
            advance()  # consume '.'
            post_dot_comments = collect_comments()
            all_comments = list(leading_comments) + list(post_dot_comments)

            next_type = peek()["type"]
            if next_type == "WRITE" or next_type == "WRITE3D":
                if context == "expression":
                    t = peek()
                    raise SyntaxError_(
                        "'.write()' is only allowed in statement context "
                        "at line %d col %d" % (t["line"], t["col"])
                    )
                write_node = parse_write_call()
                if len(all_comments) > 0:
                    write_node["leadingComments"] = all_comments
                calls.append(write_node)
                continue
            if next_type == "SUBCHAIN":
                subchain_node = parse_subchain_call()
                if len(all_comments) > 0:
                    subchain_node["leadingComments"] = all_comments
                calls.append(subchain_node)
                continue
            call = parse_call()
            if len(all_comments) > 0:
                call["leadingComments"] = all_comments
            calls.append(call)
        return calls

    def parse_write_call():
        tok = peek()
        token_type = tok["type"]
        token_line = tok["line"]
        token_col = tok["col"]

        if token_type == "WRITE":
            advance()  # consume 'write'
            expect("LPAREN", "Expect '('")
            surface = None
            p = peek()
            if p["type"] == "OUTPUT_REF":
                surface = {"type": "OutputRef", "name": advance()["lexeme"]}
            elif p["type"] == "XYZ_REF":
                surface = {"type": "XyzRef", "name": advance()["lexeme"]}
            elif p["type"] == "VEL_REF":
                surface = {"type": "VelRef", "name": advance()["lexeme"]}
            elif p["type"] == "RGBA_REF":
                surface = {"type": "RgbaRef", "name": advance()["lexeme"]}
            elif p["type"] == "MESH_REF":
                surface = {"type": "MeshRef", "name": advance()["lexeme"]}
            elif p["type"] == "IDENT" and p["lexeme"] == "none":
                surface = {"type": "OutputRef", "name": advance()["lexeme"]}
            else:
                raise SyntaxError_(
                    "write() requires an explicit surface reference "
                    "(e.g., o0, o1, xyz0, vel0, rgba0, mesh0, none) at line %d col %d"
                    % (peek()["line"], peek()["col"])
                )
            expect("RPAREN", "Expect ')'")
            return {
                "type": "Write",
                "surface": surface,
                "loc": {"line": token_line, "col": token_col},
            }
        elif token_type == "WRITE3D":
            advance()  # consume 'write3d'
            expect("LPAREN", "Expect '('")
            tex3d = None
            p = peek()
            if p["type"] in ("IDENT", "OUTPUT_REF", "VOL_REF"):
                tok_type = p["type"]
                if tok_type == "OUTPUT_REF":
                    tex3d = {"type": "OutputRef", "name": advance()["lexeme"]}
                elif tok_type == "VOL_REF":
                    tex3d = {"type": "VolRef", "name": advance()["lexeme"]}
                else:
                    tex3d = {"type": "Ident", "name": advance()["lexeme"]}
            else:
                raise SyntaxError_(
                    "Expected tex3d reference in write3d() at line %d col %d"
                    % (peek()["line"], peek()["col"])
                )
            expect("COMMA", "Expect ',' between tex3d and geo in write3d()")
            geo = None
            p = peek()
            if p["type"] in ("IDENT", "OUTPUT_REF", "GEO_REF"):
                tok_type = p["type"]
                if tok_type == "OUTPUT_REF":
                    geo = {"type": "OutputRef", "name": advance()["lexeme"]}
                elif tok_type == "GEO_REF":
                    geo = {"type": "GeoRef", "name": advance()["lexeme"]}
                else:
                    geo = {"type": "Ident", "name": advance()["lexeme"]}
            else:
                raise SyntaxError_(
                    "Expected geo reference in write3d() at line %d col %d"
                    % (peek()["line"], peek()["col"])
                )
            expect("RPAREN", "Expect ')'")
            return {
                "type": "Write3D",
                "tex3d": tex3d,
                "geo": geo,
                "loc": {"line": token_line, "col": token_col},
            }
        raise SyntaxError_(
            "Expected write or write3d at line %d col %d" % (token_line, token_col)
        )

    def parse_subchain_call():
        tok = peek()
        token_line = tok["line"]
        token_col = tok["col"]

        advance()  # consume 'subchain'
        expect("LPAREN", "Expect '(' after subchain")

        kwargs = {}
        if peek()["type"] != "RPAREN":
            if peek()["type"] == "STRING":
                kwargs["name"] = {"type": "String", "value": advance()["lexeme"]}
            elif peek()["type"] == "IDENT" and (
                tok_at(state["current"] + 1) is not None
                and tok_at(state["current"] + 1).get("type") == "COLON"
            ):
                while peek()["type"] == "IDENT" and (
                    tok_at(state["current"] + 1) is not None
                    and tok_at(state["current"] + 1).get("type") == "COLON"
                ):
                    key = advance()["lexeme"]
                    advance()  # consume ':'
                    if peek()["type"] != "STRING":
                        raise SyntaxError_(
                            "Expected string value for subchain %s at line %d col %d"
                            % (key, peek()["line"], peek()["col"])
                        )
                    kwargs[key] = {"type": "String", "value": advance()["lexeme"]}
                    if peek()["type"] == "COMMA":
                        advance()  # consume ','
        expect("RPAREN", "Expect ')' after subchain arguments")

        expect("LBRACE", "Expect '{' to start subchain body")

        body = []
        while peek()["type"] != "RBRACE":
            leading_comments = collect_comments()
            if peek()["type"] == "RBRACE":
                break
            if peek()["type"] != "DOT":
                raise SyntaxError_(
                    "Expected '.' before chain element in subchain body "
                    "at line %d col %d" % (peek()["line"], peek()["col"])
                )
            advance()  # consume '.'
            post_dot_comments = collect_comments()
            all_comments = list(leading_comments) + list(post_dot_comments)
            call = parse_call()
            if len(all_comments) > 0:
                call["leadingComments"] = all_comments
            body.append(call)

        expect("RBRACE", "Expect '}' to end subchain body")

        if len(body) == 0:
            raise SyntaxError_(
                "Subchain body cannot be empty at line %d col %d" % (token_line, token_col)
            )

        name_node = kwargs.get("name")
        id_node = kwargs.get("id")
        return {
            "type": "Subchain",
            "name": (name_node["value"] if name_node else None),
            "id": (id_node["value"] if id_node else None),
            "body": body,
            "loc": {"line": token_line, "col": token_col},
        }

    def parse_call():
        name_token = expect("IDENT", "Expected identifier")
        # Inline namespace syntax (e.g., nd.noise()) is forbidden.
        if peek()["type"] == "DOT":
            nxt = tok_at(state["current"] + 1)
            if nxt and nxt.get("type") == "IDENT":
                after = tok_at(state["current"] + 2)
                if after is not None and after.get("type") == "LPAREN":
                    raise SyntaxError_(
                        "Inline namespace syntax '%s.%s()' is not allowed. "
                        "Use 'search %s' at the start of the program instead, "
                        "at line %d col %d"
                        % (
                            name_token["lexeme"], nxt["lexeme"], name_token["lexeme"],
                            name_token["line"], name_token["col"],
                        )
                    )
        expect("LPAREN", "Expect '('")
        args = []
        kwargs = {}
        keyword = False
        if peek()["type"] != "RPAREN":
            nxt = tok_at(state["current"] + 1)
            if peek()["type"] == "IDENT" and nxt is not None and nxt.get("type") == "COLON":
                keyword = True
                parse_kwarg(kwargs)
                while peek()["type"] == "COMMA":
                    advance()
                    if peek()["type"] == "RPAREN":
                        break
                    nxt = tok_at(state["current"] + 1)
                    if not (
                        peek()["type"] == "IDENT"
                        and nxt is not None and nxt.get("type") == "COLON"
                    ):
                        t = peek()
                        raise SyntaxError_(
                            "Cannot mix positional and keyword arguments "
                            "at line %d col %d" % (t["line"], t["col"])
                        )
                    parse_kwarg(kwargs)
            else:
                args.append(parse_arg())
                while peek()["type"] == "COMMA":
                    advance()
                    if peek()["type"] == "RPAREN":
                        break
                    nxt = tok_at(state["current"] + 1)
                    if (
                        peek()["type"] == "IDENT"
                        and nxt is not None and nxt.get("type") == "COLON"
                    ):
                        t = peek()
                        raise SyntaxError_(
                            "Cannot mix positional and keyword arguments "
                            "at line %d col %d" % (t["line"], t["col"])
                        )
                    args.append(parse_arg())
        expect("RPAREN", "Expect ')'")
        call = {"type": "Call", "name": name_token["lexeme"], "args": args}
        if keyword:
            call["kwargs"] = kwargs
        name = name_token["lexeme"]
        if name == "from":
            return transform_from_invocation(call, name_token)
        # osc() as a value oscillator (not the synth.osc generator effect).
        if name == "osc":
            osc_kwargs = frozenset(["type", "min", "max", "speed", "offset", "seed"])
            has_type_kwarg = bool(kwargs) and ("type" in kwargs)
            first_arg_is_osc_kind = (
                len(args) > 0
                and args[0]
                and args[0].get("type") == "Member"
                and args[0].get("path")
                and args[0]["path"][0] == "oscKind"
            )
            is_bare_osc = len(args) == 0 and (not kwargs or len(kwargs) == 0)
            has_only_osc_kwargs = (
                bool(kwargs)
                and len(kwargs) > 0
                and all(k in osc_kwargs for k in kwargs.keys())
            )
            if has_type_kwarg or first_arg_is_osc_kind or is_bare_osc or has_only_osc_kwargs:
                return transform_osc_invocation(call, name_token)
            # Fall through to return as regular Call node for synth effect.
        if name == "midi":
            return transform_midi_invocation(call, name_token)
        if name == "audio":
            return transform_audio_invocation(call, name_token)
        # read() is a pipeline built-in for reading 2D surfaces.
        if name == "read":
            surface = None
            if len(args) > 0:
                surface = args[0]
            elif "tex" in kwargs:
                surface = kwargs["tex"]
            elif "surface" in kwargs:
                surface = kwargs["surface"]
            node = {
                "type": "Read",
                "surface": surface,
                "loc": {"line": name_token["line"], "col": name_token["col"]},
            }
            skip = kwargs.get("_skip")
            if skip and skip.get("type") == "Boolean" and skip.get("value") is True:
                node["_skip"] = True
            return node
        # read3d() reads from tex3d (and optionally geo) surfaces.
        if name == "read3d":
            tex3d = args[0] if len(args) > 0 else kwargs.get("tex3d")
            geo = args[1] if len(args) > 1 else kwargs.get("geo")
            node = {
                "type": "Read3D",
                "tex3d": tex3d,
                "geo": geo if geo else None,
                "loc": {"line": name_token["line"], "col": name_token["col"]},
            }
            skip = kwargs.get("_skip")
            if skip and skip.get("type") == "Boolean" and skip.get("value") is True:
                node["_skip"] = True
            return node
        return call

    def parse_arg():
        return parse_additive()

    def parse_additive():
        node = parse_multiplicative()
        while peek()["type"] == "PLUS" or peek()["type"] == "MINUS":
            op = advance()["type"]
            right = parse_multiplicative()
            left_val = to_number(node)
            right_val = to_number(right)
            result = left_val + right_val if op == "PLUS" else left_val - right_val
            node = {"type": "Number", "value": _make_number(result)}
        return node

    def parse_multiplicative():
        node = parse_unary()
        while peek()["type"] == "STAR" or peek()["type"] == "SLASH":
            op = advance()["type"]
            right = parse_unary()
            left_val = to_number(node)
            right_val = to_number(right)
            result = left_val * right_val if op == "STAR" else left_val / right_val
            node = {"type": "Number", "value": _make_number(result)}
        return node

    def parse_unary():
        if peek()["type"] == "PLUS":
            advance()
            return parse_unary()
        if peek()["type"] == "MINUS":
            advance()
            val = parse_unary()
            return {"type": "Number", "value": _make_number(-to_number(val))}
        return parse_primary()

    def parse_primary():
        token = peek()
        tt = token["type"]
        if tt == "NUMBER":
            advance()
            return {"type": "Number", "value": _parse_js_number(token["lexeme"])}
        if tt == "STRING":
            advance()
            return {"type": "String", "value": token["lexeme"]}
        if tt == "HEX":
            advance()
            hex_str = token["lexeme"][1:]
            a = 1.0
            if len(hex_str) == 3:
                r = int(hex_str[0] + hex_str[0], 16)
                g = int(hex_str[1] + hex_str[1], 16)
                b = int(hex_str[2] + hex_str[2], 16)
            elif len(hex_str) == 6:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
            elif len(hex_str) == 8:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                a = int(hex_str[6:8], 16) / 255
            else:
                # Lexer only emits HEX for lengths 3/6/8, so this is unreachable; mirror JS
                # (where r/g/b would be undefined) defensively by raising.
                raise SyntaxError_(
                    "Invalid hex color at line %d col %d" % (token["line"], token["col"])
                )
            return {
                "type": "Color",
                "value": [
                    _make_number(r / 255),
                    _make_number(g / 255),
                    _make_number(b / 255),
                    _make_number(a),
                ],
            }
        if tt == "LBRACKET":
            start_line = token["line"]
            start_col = token["col"]
            advance()
            elements = []
            if peek()["type"] != "RBRACKET":
                elements.append(parse_arg())
                while peek()["type"] == "COMMA":
                    advance()
                    elements.append(parse_arg())
            if peek()["type"] != "RBRACKET":
                t = peek()
                raise SyntaxError_("Expected ']' at line %d col %d" % (t["line"], t["col"]))
            advance()
            return {
                "type": "ArrayLiteral",
                "elements": elements,
                "loc": {"line": start_line, "col": start_col},
            }
        if tt == "FUNC":
            advance()
            return {"type": "Func", "src": token["lexeme"]}
        if tt == "TRUE":
            advance()
            return {"type": "Boolean", "value": True}
        if tt == "FALSE":
            advance()
            return {"type": "Boolean", "value": False}
        if tt == "IDENT":
            t1 = tok_at(state["current"] + 1)
            t2 = tok_at(state["current"] + 2)
            if (
                token["lexeme"] == "Math"
                and t1 is not None and t1.get("type") == "DOT"
                and t2 is not None and t2.get("type") == "IDENT" and t2.get("lexeme") == "PI"
            ):
                advance()
                advance()
                advance()
                return {"type": "Number", "value": _make_number(math.pi)}
            if (t1 is not None and t1.get("type") == "LPAREN") or has_call_after_dot(
                state["current"]
            ):
                chain = parse_chain("expression")
                if len(chain) == 1:
                    return chain[0]
                return {"type": "Chain", "chain": chain}
            advance()
            path = [token["lexeme"]]
            while peek()["type"] == "DOT":
                nxt = tok_at(state["current"] + 1)
                if nxt is None:
                    break
                after = tok_at(state["current"] + 2)
                if after is not None and after.get("type") == "LPAREN":
                    break
                if nxt.get("type") not in member_token_types:
                    raise SyntaxError_(
                        "Expected identifier after '.' at line %d col %d"
                        % (nxt["line"], nxt["col"])
                    )
                advance()  # consume '.'
                advance()  # consume segment token (nxt)
                path.append(nxt["lexeme"])
            if len(path) > 1:
                return {"type": "Member", "path": path}
            return {"type": "Ident", "name": path[0]}
        if tt == "OUTPUT_REF":
            advance()
            return {"type": "OutputRef", "name": token["lexeme"]}
        if tt == "SOURCE_REF":
            advance()
            return {"type": "SourceRef", "name": token["lexeme"]}
        if tt == "VOL_REF":
            advance()
            return {"type": "VolRef", "name": token["lexeme"]}
        if tt == "GEO_REF":
            advance()
            return {"type": "GeoRef", "name": token["lexeme"]}
        if tt == "XYZ_REF":
            advance()
            return {"type": "XyzRef", "name": token["lexeme"]}
        if tt == "VEL_REF":
            advance()
            return {"type": "VelRef", "name": token["lexeme"]}
        if tt == "RGBA_REF":
            advance()
            return {"type": "RgbaRef", "name": token["lexeme"]}
        if tt == "MESH_REF":
            advance()
            return {"type": "MeshRef", "name": token["lexeme"]}
        if tt == "LPAREN":
            advance()
            expr = parse_additive()
            expect("RPAREN", "Expect ')'")
            return expr
        raise SyntaxError_(
            "Unexpected token %s at line %d col %d" % (tt, token["line"], token["col"])
        )

    def to_number(node):
        if node.get("type") != "Number":
            raise SyntaxError_("Expected number")
        return node["value"]

    def parse_kwarg(obj):
        key = expect("IDENT", "Expected identifier")["lexeme"]
        expect("COLON", "Expect ':'")
        if peek()["type"] not in expr_start_tokens:
            t = peek()
            raise SyntaxError_(
                "Expected expression after '=' at line %d col %d" % (t["line"], t["col"])
            )
        obj[key] = parse_arg()

    return parse_program()


def parse_source(src):
    """Convenience: lex ``src`` with the stage-1 lexer, then parse. Returns the Program AST."""
    return parse(lex(src))
