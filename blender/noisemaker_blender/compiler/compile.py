"""compile.py -- Stage-1 entry point (port of shaders/src/lang/index.js ``compile``).

The reference ``compile(src)`` is::

    export function compile(src) {
        const tokens = lex(src)
        const ast = parse(tokens)
        return validate(ast)
    }

This module mirrors that exactly, building on the already-ported lexer, parser,
and validator. ``compile(source)`` returns the validated program dict consumed by
the expander (Stage 2)::

    {
      plans: [...],                # flattened chains of steps (see validator)
      diagnostics: [...],          # warnings AND errors (S001..S008)
      render: <name|None>,         # surface to present, from render(...) directive
      vars: [...],                 # original AST var declarations (verbatim)
      searchNamespaces: [...],     # the search-directive namespace order
      trailingComments?: [...]     # preserved trailing comments, when present
    }

``compileGraph`` (Stage-2 driver) inspects ``diagnostics``: any ``severity ==
'error'`` aborts before expansion. ``compile`` itself never throws on semantic
errors -- it reports them as diagnostics. It DOES raise on a missing ``search``
directive (mirrors the reference ``validate`` throw), which the parser already
enforces upstream as a SyntaxError.

stdlib-only and self-contained: imports only sibling compiler modules + stdlib.
"""

from __future__ import annotations

from .lexer import lex
from .parser import parse
from .validator import validate


def compile(source, options=None):  # noqa: A001 - mirrors the reference export name ``compile``
    """Parse + validate ``source`` into the validated program dict.

    Parameters
    ----------
    source : str
        DSL source code.
    options : dict, optional
        Compiler options (e.g. ``{"subchainArguments": "strict"}``).

    Returns
    -------
    dict
        The validated/transformed program (see module docstring) including its
        ``diagnostics`` list.
    """
    tokens = lex(source)
    ast = parse(tokens, options=options)
    return validate(ast)
