"""Lexer for the Noisemaker live-coding DSL.

Faithful Python port of the reference lexer (shaders/src/lang/lexer.js). Produces a
list of token dicts ``{"type", "lexeme", "line", "col"}`` with 1-based line/col, byte-for-byte
equivalent to the reference's ``lex()`` output. Pure stdlib, fully self-contained: this runs
inside Blender's bundled Python, so there are no third-party imports and no dependency on the
reference repo.

The token contract (what later compiler stages can rely on):
  - Whitespace ' ', '\\t', '\\r' is skipped (advances col by 1); '\\n' advances line, resets col=1.
  - Comments are emitted as COMMENT tokens (line ``//...`` and block ``/* ... */``), lexeme
    includes the comment delimiters.
  - Surface references are lexed BEFORE identifiers: ``o<n>``/``s<n>`` -> OUTPUT_REF/SOURCE_REF,
    ``vol<n>``/``geo<n>``/``xyz<n>``/``vel<n>``/``rgba<n>``/``mesh<n>`` -> *_REF. Note ``vol``
    and ``vel`` both start with 'v'; vol is tested first. A bare ``o``/``s``/``v`` not followed
    by the required pattern falls through to IDENT.
  - HEX color literal ``#...`` is only a HEX token when it has exactly 3, 6, or 8 hex digits
    (lexeme length 4/7/9 including '#'); otherwise '#' is an unexpected character (error).
  - Arrow function ``() => expr`` becomes a FUNC token whose lexeme is the trimmed expr text
    (the ``()`` / ``=>`` and surrounding spaces are stripped); the scan stops at a top-level
    ',' ';' newline or '}', or at the matching ')'.
  - Numbers: leading-dot (``.5``) and ``int[.frac]`` forms; a trailing '.' not followed by a
    digit is a separate DOT token.
  - Strings: triple-quoted ``\"\"\"...\"\"\"`` (multi-line; checked before single quotes), and
    single-line ``"..."`` / ``'...'`` with backslash escapes. The STRING lexeme is the content
    WITHOUT the surrounding quotes. Unterminated strings/comments raise SyntaxError.
  - Identifiers ``[A-Za-z_][A-Za-z0-9_]*``; reserved words map to keyword token types.
  - A trailing EOF token (lexeme "") is always appended.

The line/col arithmetic mirrors the reference exactly, including a couple of spots where the
reference recomputes col in a way that only matters for multi-line tokens.
"""

from __future__ import annotations

import re

from .lang_data import DIAGNOSTICS

_OUTPUT_REF_RE = re.compile(r"^o[0-7]$")

# Reserved DSL keyword -> token-type map. Single source of truth (mirrors RESERVED_KEYWORDS
# in the reference lexer.js, shared there with namespace validation).
RESERVED_KEYWORDS = {
    "let": "LET",
    "render": "RENDER",
    "write": "WRITE",
    "write3d": "WRITE3D",
    "true": "TRUE",
    "false": "FALSE",
    "if": "IF",
    "elif": "ELIF",
    "else": "ELSE",
    "break": "BREAK",
    "continue": "CONTINUE",
    "return": "RETURN",
    "search": "SEARCH",
    "subchain": "SUBCHAIN",
}


class SyntaxError_(SyntaxError):
    """Raised on malformed source (mirrors the reference's thrown SyntaxError).

    Named with a trailing underscore so it does not shadow the builtin ``SyntaxError`` at the
    use sites below, while still subclassing it so ``except SyntaxError`` also catches it.
    """

    diagnostic: dict | None = None


# Characters JS String.prototype.trim() removes. DSL exprs are ASCII, but match the JS set so
# FUNC lexemes are identical to the reference even for unusual whitespace.
_JS_TRIM_CHARS = " \t\n\r\v\f                 　﻿"


def _is_digit(c):
    return "0" <= c <= "9"


def _is_letter(c):
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


def _is_hex(c):
    return ("0" <= c <= "9") or ("a" <= c <= "f") or ("A" <= c <= "F")


def lex(src):
    """Tokenize DSL source.

    :param src: source code string
    :returns: list of token dicts {"type","lexeme","line","col"}
    """
    tokens = []
    n = len(src)
    i = 0
    line = 1
    col = 1

    def add(type_, lexeme, ln, cl):
        tokens.append({"type": type_, "lexeme": lexeme, "line": ln, "col": cl})

    # Only scan source coordinates on failure. Successful tokens and legacy
    # error messages retain their existing position bookkeeping.
    def fail(code, message, start, end):
        error_line = 1
        column = 1
        for ch_ in src[:start]:
            if ch_ == "\n":
                error_line += 1
                column = 1
            else:
                column += 2 if ord(ch_) > 0xFFFF else 1
        start_u16 = len(src[:start].encode("utf-16-le")) // 2
        end_u16 = len(src[:end].encode("utf-16-le")) // 2
        err = SyntaxError_(message)
        err.diagnostic = {
            "code": code,
            "stage": DIAGNOSTICS[code]["stage"],
            "severity": DIAGNOSTICS[code]["severity"],
            "message": message,
            "location": {"line": error_line, "column": column},
            "span": {"start": start_u16, "end": end_u16},
        }
        raise err

    # Bounds-safe character access. JS returns ``undefined`` for out-of-range string indices,
    # which never equals a real char and is never a digit/letter; "" reproduces that behavior.
    def at(idx):
        if 0 <= idx < n:
            return src[idx]
        return ""

    keywords = RESERVED_KEYWORDS

    while i < n:
        ch = src[i]

        if ch == " " or ch == "\t" or ch == "\r":
            i += 1
            col += 1
            continue
        if ch == "\n":
            i += 1
            line += 1
            col = 1
            continue

        start_line = line
        start_col = col

        # line comments - emit as COMMENT token
        if ch == "/" and at(i + 1) == "/":
            j = i + 2
            while j < n and src[j] != "\n":
                j += 1
            text = src[i:j]
            add("COMMENT", text, start_line, start_col)
            col += len(text.encode("utf-16-le")) // 2
            i = j
            continue

        # block comments - emit as COMMENT token
        if ch == "/" and at(i + 1) == "*":
            j = i + 2
            end_line = line
            end_col = col + 2
            while j < n and not (src[j] == "*" and at(j + 1) == "/"):
                if src[j] == "\n":
                    end_line += 1
                    end_col = 1
                else:
                    end_col += 2 if ord(src[j]) > 0xFFFF else 1
                j += 1
            if j >= n:
                fail(
                    "L003",
                    "Unterminated comment at line %d col %d" % (start_line, start_col),
                    i,
                    n,
                )
            j += 2
            text = src[i:j]
            add("COMMENT", text, start_line, start_col)
            line = end_line
            col = end_col + 2
            i = j
            continue

        # output or source reference
        if (ch == "o" or ch == "s") and _is_digit(at(i + 1)):
            j = i + 1
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            token_type = "OUTPUT_REF" if ch == "o" else "SOURCE_REF"
            is_member_segment = bool(tokens and tokens[-1]["type"] == "DOT")
            if token_type == "OUTPUT_REF" and not is_member_segment and not _OUTPUT_REF_RE.match(lexeme):
                fail(
                    "L004",
                    f"Output surface reference '{lexeme}' is out of range; expected o0-o7 at line {start_line} col {start_col}",
                    i,
                    j,
                )
            add(token_type, lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # volume reference (vol0-vol7)
        if ch == "v" and at(i + 1) == "o" and at(i + 2) == "l" and _is_digit(at(i + 3)):
            j = i + 3
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("VOL_REF", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # geometry reference (geo0-geo7)
        if ch == "g" and at(i + 1) == "e" and at(i + 2) == "o" and _is_digit(at(i + 3)):
            j = i + 3
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("GEO_REF", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # xyz reference (xyz0-xyz7) - agent position surfaces
        if ch == "x" and at(i + 1) == "y" and at(i + 2) == "z" and _is_digit(at(i + 3)):
            j = i + 3
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("XYZ_REF", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # vel reference (vel0-vel7) - agent velocity surfaces
        if ch == "v" and at(i + 1) == "e" and at(i + 2) == "l" and _is_digit(at(i + 3)):
            j = i + 3
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("VEL_REF", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # rgba reference (rgba0-rgba7) - agent color surfaces
        if (
            ch == "r"
            and at(i + 1) == "g"
            and at(i + 2) == "b"
            and at(i + 3) == "a"
            and _is_digit(at(i + 4))
        ):
            j = i + 4
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("RGBA_REF", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # mesh reference (mesh0-mesh7) - mesh geometry surfaces
        if (
            ch == "m"
            and at(i + 1) == "e"
            and at(i + 2) == "s"
            and at(i + 3) == "h"
            and _is_digit(at(i + 4))
        ):
            j = i + 4
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("MESH_REF", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        # html hex color literal
        if ch == "#":
            j = i + 1
            while j < n and _is_hex(src[j]):
                j += 1
            length = j - i
            if length == 4 or length == 7 or length == 9:
                lexeme = src[i:j]
                add("HEX", lexeme, start_line, start_col)
                col += length
                i = j
                continue

        # arrow function expression (() => expr)
        if ch == "(" and at(i + 1) == ")":
            j = i + 2
            while j < n and (src[j] == " " or src[j] == "\t"):
                j += 1
            if at(j) == "=" and at(j + 1) == ">":
                j += 2
                while j < n and (src[j] == " " or src[j] == "\t"):
                    j += 1
                depth = 0
                expr_start = j
                while j < n:
                    c = src[j]
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        if depth == 0:
                            break
                        depth -= 1
                    elif depth == 0:
                        if c == "," or c == ";" or c == "\n" or c == "}":
                            break
                    j += 1
                expr = src[expr_start:j].strip(_JS_TRIM_CHARS)
                add("FUNC", expr, start_line, start_col)
                col += j - i
                i = j
                continue

        if ch == "." and _is_digit(at(i + 1)):
            j = i + 1
            while j < n and _is_digit(src[j]):
                j += 1
            lexeme = src[i:j]
            add("NUMBER", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue
        if ch == ".":
            add("DOT", ".", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "(":
            add("LPAREN", "(", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == ")":
            add("RPAREN", ")", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "{":
            add("LBRACE", "{", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "}":
            add("RBRACE", "}", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "[":
            add("LBRACKET", "[", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "]":
            add("RBRACKET", "]", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == ",":
            add("COMMA", ",", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == ":":
            add("COLON", ":", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "=":
            add("EQUAL", "=", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == ";":
            add("SEMICOLON", ";", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "+":
            add("PLUS", "+", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "-":
            add("MINUS", "-", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "*":
            add("STAR", "*", start_line, start_col)
            i += 1
            col += 1
            continue
        if ch == "/":
            add("SLASH", "/", start_line, start_col)
            i += 1
            col += 1
            continue

        # Triple-quoted strings (multi-line) - must check before single quotes
        if ch == '"' and at(i + 1) == '"' and at(i + 2) == '"':
            j = i + 3
            # Find closing """
            while j < n - 2:
                if src[j] == '"' and src[j + 1] == '"' and src[j + 2] == '"':
                    break
                if src[j] == "\n":
                    line += 1
                    col = 0  # Will be set correctly after loop
                j += 1
            if j >= n - 2 or not (
                at(j) == '"' and at(j + 1) == '"' and at(j + 2) == '"'
            ):
                fail(
                    "L002",
                    "Unterminated triple-quoted string at line %d col %d"
                    % (start_line, start_col),
                    i,
                    n,
                )
            # Extract string content without the triple quotes
            content = src[i + 3 : j]
            add("STRING", content, start_line, start_col)
            # Update position past closing """
            lines = content.split("\n")
            if len(lines) > 1:
                col = len(lines[-1].encode("utf-16-le")) // 2 + 4  # +3 for closing """ +1 for next char
            else:
                col += len(src[i : j + 3].encode("utf-16-le")) // 2
            i = j + 3
            continue

        if ch == '"' or ch == "'":
            quote = ch
            j = i + 1
            while j < n and src[j] != quote and src[j] != "\n":
                # Handle escape sequences
                if src[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            if j >= n or src[j] == "\n":
                fail(
                    "L002",
                    "Unterminated string literal at line %d col %d" % (line, col),
                    i,
                    j,
                )
            # Extract string content without quotes
            content = src[i + 1 : j]
            add("STRING", content, start_line, start_col)
            col += len(src[i : j + 1].encode("utf-16-le")) // 2
            i = j + 1
            continue

        if _is_digit(ch):
            j = i
            while j < n and _is_digit(src[j]):
                j += 1
            if at(j) == "." and _is_digit(at(j + 1)):
                j += 1
                while j < n and _is_digit(src[j]):
                    j += 1
            lexeme = src[i:j]
            add("NUMBER", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        if _is_letter(ch) or ch == "_":
            j = i
            while j < n and (_is_letter(src[j]) or _is_digit(src[j]) or src[j] == "_"):
                j += 1
            lexeme = src[i:j]
            if lexeme in keywords:
                add(keywords[lexeme], lexeme, start_line, start_col)
            else:
                add("IDENT", lexeme, start_line, start_col)
            col += j - i
            i = j
            continue

        fail(
            "L001",
            "Unexpected character '%s' at line %d col %d" % (ch, line, col),
            i,
            i + 1,
        )

    add("EOF", "", line, col)
    return tokens
