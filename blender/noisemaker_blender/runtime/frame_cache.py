"""Provenance-checked binary float snapshots for prepared background rendering.

A cache is prepared on a qualified GPU host. Reading it does not constitute
fresh background GPU evaluation. Pixel data is stored only in binary NPY files;
JSON sidecars contain provenance and hashes, never image payloads.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np

_REQUIRED = frozenset(('source', 'inputs', 'parameters', 'frame', 'subframe', 'fps',
                       'fps_base', 'origin_frame', 'loop_seconds', 'offset', 'width',
                       'height', 'color_role', 'alpha_mode', 'simulation', 'mode'))


class CacheError(ValueError):
    """A frame cannot be consumed with the requested provenance."""


def _identity(provenance):
    data = dict(provenance)
    missing = _REQUIRED.difference(data)
    if missing:
        raise CacheError('Incomplete cache identity: %s' % ', '.join(sorted(missing)))
    if data['mode'] != 'timeline':
        raise CacheError('Render caches accept timeline evaluation only')
    for dim in ('width', 'height'):
        if type(data[dim]) is not int or data[dim] <= 0:
            raise CacheError('Cache %s must be a positive integer' % dim)
    try:
        encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise CacheError('Cache identity must be finite JSON metadata') from error
    return json.loads(encoded), hashlib.sha256(encoded.encode()).hexdigest()


class FrameCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def write(self, pixels, provenance):
        identity, key = _identity(provenance)
        values = np.asarray(pixels, dtype=np.float32)
        expected = (identity['height'], identity['width'], 4)
        if values.shape != expected or not np.isfinite(values).all():
            raise CacheError('Cache pixels must be finite float RGBA with identity dimensions')
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (key + '.npy')
        staged = []
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.npy', delete=False) as stream:
                staged.append(Path(stream.name))
                np.save(stream, values, allow_pickle=False)
                stream.flush()
                os.fsync(stream.fileno())
            digest = hashlib.sha256(staged[0].read_bytes()).hexdigest()
            metadata = dict(version=1, identity=identity, sha256=digest,
                            shape=list(values.shape), dtype='float32')
            with tempfile.NamedTemporaryFile(dir=self.directory, mode='w', suffix='.json', delete=False) as stream:
                staged.append(Path(stream.name))
                json.dump(metadata, stream, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            # Data first, metadata last. Interrupted/concurrent writes can only
            # produce a hash mismatch, never acceptance of stale pixel data.
            os.replace(staged[0], path)
            os.replace(staged[1], path.with_suffix('.json'))
            return path
        finally:
            for temporary in staged:
                temporary.unlink(missing_ok=True)

    def read(self, provenance):
        identity, key = _identity(provenance)
        path = self.directory / (key + '.npy')
        try:
            metadata = json.loads(path.with_suffix('.json').read_text())
            payload = path.read_bytes()
            if (metadata.get('version') != 1 or metadata.get('identity') != identity
                    or metadata.get('sha256') != hashlib.sha256(payload).hexdigest()
                    or metadata.get('dtype') != 'float32'):
                raise CacheError('Cache identity or payload hash mismatch: %s' % key)
            # Read the exact bytes hashed above, avoiding a concurrent-file race.
            import io
            values = np.load(io.BytesIO(payload), allow_pickle=False)
            shape = (identity['height'], identity['width'], 4)
            if (values.dtype != np.float32 or values.shape != shape
                    or metadata.get('shape') != list(shape) or not np.isfinite(values).all()):
                raise CacheError('Invalid cached float image: %s' % key)
            return values
        except (OSError, ValueError, TypeError, AttributeError) as error:
            if isinstance(error, CacheError):
                raise
            raise CacheError('Missing or invalid cached frame %s: %s' % (identity['frame'], error)) from error

    def validate(self, requests):
        """Check every frame before a render writes any output; return binary paths."""
        paths = []
        for request in requests:
            self.read(request)
            _, key = _identity(request)
            paths.append(self.directory / (key + '.npy'))
        return paths
