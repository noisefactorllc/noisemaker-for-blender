"""Helpers for the DSL string fields that opt into escape decoding."""

import json


def decode_json_string_literal_content(raw):
    """Decode JSON escapes while preserving legacy unknown escapes."""
    try:
        return json.loads('"%s"' % raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        decoded = []
        escapes = {
            "'": "'",
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "v": "\v",
            "0": "\0",
        }
        i = 0
        while i < len(raw):
            if raw[i] != "\\" or i + 1 >= len(raw):
                decoded.append(raw[i])
                i += 1
                continue
            i += 1
            next_char = raw[i]
            decoded.append(escapes.get(next_char, "\\" + next_char))
            i += 1
        return "".join(decoded)
