"""Bounded, identity-verified state snapshots and exact fixed-step replay."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Callable


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class CheckpointIdentity:
    source: str
    parameters: object
    inputs: object
    width: int
    height: int
    seed: object
    time_mapping: object
    simulation_policy: object
    fingerprint: str = field(init=False)

    def __post_init__(self):
        if not isinstance(self.source, str) or self.width <= 0 or self.height <= 0:
            raise ValueError("checkpoint source and dimensions must be valid")
        material = (self.source, self.parameters, self.inputs, self.width,
                    self.height, self.seed, self.time_mapping, self.simulation_policy)
        object.__setattr__(self, "fingerprint", hashlib.sha256(_canonical(material)).hexdigest())


@dataclass(frozen=True)
class Checkpoint:
    identity: str
    step: int
    payload: bytes
    checksum: str


class CheckpointStore:
    def __init__(self, *, max_items: int = 8, max_bytes: int = 64 * 1024 * 1024):
        if max_items <= 0 or max_bytes <= 0:
            raise ValueError("checkpoint bounds must be positive")
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._entries: list[Checkpoint] = []
        self._bytes = 0

    def put(self, identity: CheckpointIdentity, step: int, payload: bytes) -> None:
        if not isinstance(step, int) or isinstance(step, bool) or step < 0:
            raise ValueError("checkpoint step must be nonnegative")
        if not isinstance(payload, bytes) or not payload or len(payload) > self.max_bytes:
            raise ValueError("checkpoint payload must be nonempty bytes within budget")
        self._entries = [entry for entry in self._entries
                         if not (entry.identity == identity.fingerprint and entry.step == step)]
        self._bytes = sum(len(entry.payload) for entry in self._entries)
        entry = Checkpoint(identity.fingerprint, step, bytes(payload), hashlib.sha256(payload).hexdigest())
        self._entries.append(entry)
        self._bytes += len(entry.payload)
        while len(self._entries) > self.max_items or self._bytes > self.max_bytes:
            removed = self._entries.pop(0)
            self._bytes -= len(removed.payload)

    def latest(self, identity: CheckpointIdentity, at_or_before: int) -> Checkpoint | None:
        candidates = [entry for entry in self._entries
                      if entry.identity == identity.fingerprint and entry.step <= at_or_before]
        if not candidates:
            return None
        entry = max(candidates, key=lambda item: item.step)
        if hashlib.sha256(entry.payload).hexdigest() != entry.checksum:
            raise ValueError("checkpoint checksum mismatch")
        return entry

    def invalidate(self, identity: CheckpointIdentity | None = None) -> None:
        if identity is None:
            self._entries.clear()
        else:
            self._entries = [entry for entry in self._entries if entry.identity != identity.fingerprint]
        self._bytes = sum(len(entry.payload) for entry in self._entries)


@dataclass(frozen=True)
class ReplayStatus:
    target_step: int
    completed_steps: int
    total_steps: int
    complete: bool


class ReplayCancelled(Exception):
    """Replay stopped before the requested state was reached."""


class ReplayPending(Exception):
    """A bounded replay made progress but has not reached the requested state."""
    def __init__(self, status: ReplayStatus):
        self.status = status
        super().__init__("replay pending at step %d of %d" % (
            status.completed_steps, status.target_step))


class ReplayController:
    def __init__(self, store: CheckpointStore, *, checkpoint_interval: int = 24,
                 max_steps_per_seek: int = 100000):
        if checkpoint_interval <= 0 or max_steps_per_seek <= 0:
            raise ValueError("replay bounds must be positive")
        self.store = store
        self.checkpoint_interval = checkpoint_interval
        self.max_steps_per_seek = max_steps_per_seek
        self._identity = None
        self._step = None
        self.status = ReplayStatus(0, 0, 0, False)

    def invalidate(self) -> None:
        """Call when GPU state is externally changed or lost."""
        self._identity = None
        self._step = None

    def seek(self, target_step: int, identity: CheckpointIdentity, *,
             reset: Callable[[], None], restore: Callable[[bytes], None],
             advance: Callable[[int], None], snapshot: Callable[[], bytes] | None = None,
             cancel: Callable[[], bool] | None = None,
             progress: Callable[[ReplayStatus], None] | None = None,
             max_steps: int | None = None) -> ReplayStatus:
        if not isinstance(target_step, int) or isinstance(target_step, bool) or target_step < 0:
            raise ValueError("target step must be nonnegative")
        if max_steps is not None and (not isinstance(max_steps, int) or isinstance(max_steps, bool)
                                      or max_steps <= 0):
            raise ValueError("max_steps must be a positive integer")
        if self._identity == identity.fingerprint and self._step == target_step:
            self.status = ReplayStatus(target_step, target_step, 0, True)
            return self.status
        checkpoint = self.store.latest(identity, target_step)
        current_is_usable = (self._identity == identity.fingerprint
                             and self._step is not None and self._step <= target_step
                             and (checkpoint is None or self._step >= checkpoint.step))
        start = self._step if current_is_usable else (checkpoint.step if checkpoint else 0)
        if target_step - start > self.max_steps_per_seek:
            raise ValueError("replay exceeds max_steps_per_seek")
        if not current_is_usable:
            if checkpoint:
                restore(checkpoint.payload)
            else:
                reset()
        self._identity = identity.fingerprint
        self._step = start
        self.status = ReplayStatus(target_step, start, target_step - start, start == target_step)
        if progress:
            progress(self.status)
        stop = target_step if max_steps is None else min(target_step, start + max_steps)
        for step in range(start + 1, stop + 1):
            if cancel and cancel():
                self.invalidate()
                self.status = ReplayStatus(target_step, step - 1, target_step - start, False)
                if progress:
                    progress(self.status)
                raise ReplayCancelled("replay canceled before step %d" % step)
            advance(step)
            self._step = step
            if snapshot is not None and step % self.checkpoint_interval == 0:
                self.store.put(identity, step, snapshot())
            self.status = ReplayStatus(target_step, step, target_step - start, step == target_step)
            if progress:
                progress(self.status)
        if self._step != target_step:
            self.status = ReplayStatus(target_step, self._step, target_step - start, False)
            raise ReplayPending(self.status)
        return self.status
