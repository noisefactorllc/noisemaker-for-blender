"""Borrowed GPU output descriptors for persistent render sessions."""

from dataclasses import dataclass
import weakref


class StaleOutputError(RuntimeError):
    """A borrowed output no longer belongs to the current session generation."""


@dataclass(frozen=True)
class OutputDescriptor:
    width: int
    height: int
    format: str
    color_space: str = "scene_linear"
    alpha_mode: str = "premultiplied"

    @property
    def colorSpace(self):
        return self.color_space

    @property
    def alphaMode(self):
        return self.alpha_mode


@dataclass(frozen=True, slots=True)
class OutputHandle:
    """A session-owned texture reference, valid until evaluation or graph replacement."""

    _session: object
    _epoch: int
    name: str
    descriptor: OutputDescriptor
    generation: int
    frame: int
    subframe: float
    source_id: str

    def __init__(self, session, epoch, name, descriptor, generation, frame, subframe,
                 source_id):
        object.__setattr__(self, "_session", weakref.ref(session))
        object.__setattr__(self, "_epoch", epoch)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "descriptor", descriptor)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "subframe", subframe)
        object.__setattr__(self, "source_id", source_id)

    def _validated_session(self):
        session = self._session()
        if session is None or session.closed or session._epoch != self._epoch:
            raise StaleOutputError("output belongs to an expired session generation")
        return session

    @property
    def texture(self):
        session = self._validated_session()
        return session._texture(self.name)

    @property
    def provenance(self):
        return {
            "source_id": self.source_id,
            "generation": self.generation,
            "frame": self.frame,
            "subframe": self.subframe,
            "width": self.descriptor.width,
            "height": self.descriptor.height,
        }
