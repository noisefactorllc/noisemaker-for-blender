"""Structured runtime diagnostics (reference dd4606ea/e24c844f lineage).

Mirrors the reference's ``shaders/src/runtime/backends/diagnostics.js``
``DIAGNOSTIC_CODES`` / ``DiagnosticCollector``, adapted to the port's single
Blender backend: the compile/link/uniform-block union members have no analogue
here (Blender's ``gpu.types.GPUShader`` raises on compile error and exposes no
info log, has no link stage, and the port throws no uniform-block object — the
gap006 disposition), so only the engine-independent "silent fallback" codes are
carried: recorded-rather-than-thrown behavior that keeps its historical output
while surfacing a queryable record.

Record shape (plain dicts, like the reference):
  - ``code``     legacy machine code;
  - ``stage``    which pipeline stage fell back;
  - ``backend``  ``'blender'``;
  - plus per-stage fields (``spec``/``fallback`` for dimensions,
    ``format``/``fallback`` for texture formats).
"""

DIAGNOSTIC_CODES = {
    "UNKNOWN_FORMAT_FALLBACK": "ERR_UNKNOWN_FORMAT_FALLBACK",
    "DIMENSION_FALLBACK": "ERR_DIMENSION_FALLBACK",
}


class DiagnosticCollector:
    """A capped, queryable collector for structured diagnostics that are
    recorded rather than thrown — the historically-silent dimension and texture
    format fallbacks keep their historical behavior (no new
    rejection) but now surface structured records instead of pure silence."""

    def __init__(self, cap=64):
        self.cap = cap
        self.records = []

    def add(self, record):
        self.records.append(record)
        if len(self.records) > self.cap:
            self.records.pop(0)
        return record

    def clear(self):
        del self.records[:]
