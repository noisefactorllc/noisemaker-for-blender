"""lang_data.py -- static language data for the in-Blender DSL validator.

Ports the small reference language-data modules that the validator/transform
stages depend on, with NO behavioral change:

  * ``shaders/src/lang/diagnostics.js``  -> ``DIAGNOSTICS``
  * ``shaders/src/lang/std_enums.js``    -> ``STD_ENUMS`` (channel/color/oscType/
    oscKind/midiMode/audioBand/palette)
  * ``shaders/src/lang/enumPaths.js``    -> ``normalize_member_path`` /
    ``path_starts_with`` / ``apply_enum_prefix`` / ``strip_enum_prefix``
  * ``shaders/src/lang/paramAliases.js`` constant ``ALIAS_EOL_DATE`` and the
    deprecation-warning string format.

The reference builds ``stdEnums.palette`` from ``palettes.js`` (i.e.
``share/palettes.json``) with ``value`` == the palette's index in insertion
order. That JSON is NOT vendored into the addon, so the 56 palette names are
embedded here verbatim (same order as ``share/palettes.json``) to reproduce the
enum exactly. Nothing else in the validator depends on palette data.

stdlib-only and self-contained: this module imports nothing.
"""

from __future__ import annotations

# --- diagnostics.js -----------------------------------------------------------
# code -> {stage, severity, message}. Only ``severity`` and ``message`` are read
# by the validator (``message`` as the default text, ``severity`` copied into
# each emitted diagnostic).
DIAGNOSTICS = {
    "L001": {"stage": "lexer", "severity": "error", "message": "Unexpected character"},
    "L002": {"stage": "lexer", "severity": "error", "message": "Unterminated string literal"},
    "P001": {"stage": "parser", "severity": "error", "message": "Unexpected token"},
    "P002": {"stage": "parser", "severity": "error", "message": "Expected closing parenthesis"},
    "S001": {"stage": "semantic", "severity": "error", "message": "Unknown identifier"},
    "S002": {"stage": "semantic", "severity": "warning", "message": "Argument out of range"},
    "S003": {"stage": "semantic", "severity": "error", "message": "Variable used before assignment"},
    "S004": {"stage": "semantic", "severity": "error", "message": "Cannot assign null or undefined"},
    "S005": {"stage": "semantic", "severity": "error", "message": "Illegal chain structure"},
    "S006": {"stage": "semantic", "severity": "error", "message": "Starter chain missing write() call"},
    "S007": {"stage": "semantic", "severity": "warning", "message": "Deprecated parameter alias"},
    "S008": {"stage": "semantic", "severity": "warning", "message": "Deprecated effect"},
    "R001": {"stage": "runtime", "severity": "error", "message": "Runtime error"},
}

# --- paramAliases.js ----------------------------------------------------------
ALIAS_EOL_DATE = "2026-09-01"


def param_alias_warning(old_name: str, new_name: str) -> str:
    """The exact deprecation-warning string the reference produces (S007)."""
    return (
        "param '%s' is deprecated, use '%s' instead. "
        "Aliases will be removed on %s." % (old_name, new_name, ALIAS_EOL_DATE)
    )


def effect_alias_warning(old_op_name: str, new_name: str) -> str:
    """The exact deprecation-warning string for a deprecated effect (S008).

    Mirrors ``effectAliases.checkEffectAlias``: the displayed old name is the
    bare func (last dotted segment) when the op is namespaced.
    """
    bare = old_op_name.split(".")[-1] if "." in old_op_name else old_op_name
    return (
        "effect '%s' is deprecated, use '%s' instead. "
        "Aliases will be removed on %s." % (bare, new_name, ALIAS_EOL_DATE)
    )


# --- std_enums.js -------------------------------------------------------------
# Palette names in insertion order (== share/palettes.json key order). The enum
# value of each is its index, matching the reference paletteEnum construction.
_PALETTE_NAMES = [
    "none", "seventiesShirt", "fiveG", "afterimage", "barstow", "bloob",
    "blueSkies", "brushedMetal", "burningSky", "california", "columbia",
    "cottonCandy", "darkSatin", "dealerHat", "dreamy", "eventHorizon",
    "ghostly", "grayscale", "hazySunset", "heatmap", "hypercolor", "jester",
    "justBlue", "justCyan", "justGreen", "justPurple", "justRed", "justYellow",
    "mars", "modesto", "moss", "neptune", "netOfGems", "organic", "papaya",
    "radioactive", "royal", "santaCruz", "sherbet", "sherbetDouble",
    "silvermane", "skykissed", "solaris", "spooky", "springtime", "sproingtime",
    "sulphur", "summoning", "superhero", "toxic", "tropicalia", "tungsten",
    "vaporwave", "vibrant", "vintage", "vintagePhoto",
]


def _num(value):
    return {"type": "Number", "value": value}


_PALETTE_ENUM = {name: _num(index) for index, name in enumerate(_PALETTE_NAMES)}

_OSC_KIND_ENUM = {
    "sine": _num(0),
    "tri": _num(1),
    "saw": _num(2),
    "sawInv": _num(3),
    "square": _num(4),
    "noise": _num(5),
    "noise1d": _num(5),
    "noise2d": _num(6),
}

_MIDI_MODE_ENUM = {
    "noteChange": _num(0),
    "gateNote": _num(1),
    "gateVelocity": _num(2),
    "triggerNote": _num(3),
    "velocity": _num(4),
}

_AUDIO_BAND_ENUM = {
    "low": _num(0),
    "mid": _num(1),
    "high": _num(2),
    "vol": _num(3),
    "raw": _num(4),
}

STD_ENUMS = {
    "channel": {
        "r": _num(0),
        "g": _num(1),
        "b": _num(2),
        "a": _num(3),
    },
    "color": {
        "mono": _num(0),
        "rgb": _num(1),
        "hsv": _num(2),
    },
    "oscType": {
        "sine": _num(0),
        "linear": _num(1),
        "sawtooth": _num(2),
        "sawtoothInv": _num(3),
        "square": _num(4),
        "noise1d": _num(5),
        "noise2d": _num(6),
    },
    "oscKind": _OSC_KIND_ENUM,
    "midiMode": _MIDI_MODE_ENUM,
    "audioBand": _AUDIO_BAND_ENUM,
    "palette": _PALETTE_ENUM,
}


# --- enumPaths.js -------------------------------------------------------------
def normalize_member_path(value):
    """Port of ``normalizeMemberPath``. Returns a list[str] or None."""
    if not value and value != 0:
        return None
    if isinstance(value, list):
        parts = [seg for seg in value if isinstance(seg, str) and len(seg)]
        return parts if parts else None
    if isinstance(value, str):
        parts = [seg.strip() for seg in value.split(".")]
        parts = [seg for seg in parts if seg]
        return parts if parts else None
    if isinstance(value, bool):
        # JS ``typeof true === 'boolean'`` falls through to ``return null``.
        return None
    if isinstance(value, (int, float)):
        return [_js_number_str(value)]
    return None


def _js_number_str(value):
    """Render a number the way ``String(n)`` would in JS (no trailing .0)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def path_starts_with(path, prefix):
    """Port of ``pathStartsWith``."""
    if not isinstance(prefix, list) or not len(prefix):
        return True
    if not isinstance(path, list) or len(path) < len(prefix):
        return False
    for i in range(len(prefix)):
        if path[i] != prefix[i]:
            return False
    return True


def apply_enum_prefix(path, prefix):
    """Port of ``applyEnumPrefix``."""
    if not isinstance(path, list) or not len(path):
        return path
    if not isinstance(prefix, list) or not len(prefix):
        return list(path)
    if path_starts_with(path, prefix):
        return list(path)
    for i in range(1, len(prefix)):
        suffix = prefix[i:]
        if path_starts_with(path, suffix):
            return prefix[:i] + path
    return prefix + path


def strip_enum_prefix(path, prefix):
    """Port of ``stripEnumPrefix``."""
    normalized_path = normalize_member_path(path)
    normalized_prefix = normalize_member_path(prefix)
    if not normalized_path or not len(normalized_path):
        return normalized_path
    if not normalized_prefix or not len(normalized_prefix):
        return normalized_path
    if path_starts_with(normalized_path, normalized_prefix):
        return normalized_path[len(normalized_prefix):]
    for i in range(len(normalized_prefix) - 1, 0, -1):
        suffix = normalized_prefix[i:]
        if path_starts_with(normalized_path, suffix):
            return normalized_path[len(suffix):]
    return normalized_path
