"""Noisemaker for Blender DSL compiler package (lexer/parser/validator/graph port).

Stage-1 (``compile``) mirrors the reference ``shaders/src/lang/index.js``:
``compile(source)`` == lex -> parse -> validate, returning the validated program
(with diagnostics) that the expander consumes.

Stage-2 (``expand``) mirrors ``shaders/src/runtime/expander.js``: it turns the
validated program's logical graph (``plans``) into a render graph
(``{passes, programs, textureSpecs, renderSurface}``).

Stage-3 (``compile_graph``) mirrors ``shaders/src/runtime/compiler.js``
``compileGraph`` -- it drives ``compile`` -> ``expand`` -> resource allocation
(``resources.allocate_resources``) and assembles the final graph, then applies
the same normalisation ``tools/export-graph.mjs`` applies. ``compile_graph(
source)`` returns the NORMALIZED render graph -- the exact object that golden
producer writes (``{id, source, renderSurface, passes, allocations, textures,
programs}``) and that ``runtime/graph_loader.Graph`` consumes. With it the addon
can produce render graphs with no external reference engine.
"""

from .lexer import lex
from .parser import parse, parse_source
from .validator import validate
from .compile import compile
from .transform import replace_effect, list_steps, get_compatible_replacements
from .expander import expand
from .palette_expansion import expand_palette
from .resources import allocate_resources, analyze_liveness
from .compiler import (
    compile_graph,
    hash_source,
    extract_texture_specs,
    CompilationError,
    ExpansionError,
)

__all__ = [
    "lex",
    "parse",
    "parse_source",
    "validate",
    "compile",
    "replace_effect",
    "list_steps",
    "get_compatible_replacements",
    "expand",
    "expand_palette",
    "allocate_resources",
    "analyze_liveness",
    "compile_graph",
    "hash_source",
    "extract_texture_specs",
    "CompilationError",
    "ExpansionError",
]
