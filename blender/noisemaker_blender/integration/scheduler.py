"""Bounded, engine-free live work queue; Blender timer owns GPU execution."""
from __future__ import annotations
from dataclasses import dataclass, field

from ..runtime.checkpoints import ReplayPending


@dataclass
class LiveStatus:
    last_good: object = None
    error: str = ""
    dirty: set[str] = field(default_factory=set)
    paused: bool = False
    next_due: float = 0.0
    generation: int = 0
    replay_progress: object = None


@dataclass
class _Slot:
    produce: object
    status: LiveStatus
    continuous: bool = False
    dependency_seen: dict[str, int] = field(default_factory=dict)
    interval: float | None = None


class LiveScheduler:
    def __init__(self, *, debounce_seconds=0.15, min_interval=1 / 60):
        if debounce_seconds < 0 or min_interval <= 0:
            raise ValueError("scheduler intervals must be valid")
        self.debounce_seconds = debounce_seconds
        self.min_interval = min_interval
        self._slots: dict[str, _Slot] = {}
        self._suspended: set[str] = set()
        self._cursor = 0

    def register(self, key, produce, *, continuous=False):
        if not key or not callable(produce):
            raise ValueError("live work needs a key and producer")
        if key in self._slots:
            self._slots[key].produce = produce
            self._slots[key].continuous = continuous
        else:
            self._slots[key] = _Slot(produce, LiveStatus(), continuous)

    def unregister(self, key):
        self._slots.pop(key, None)

    def status(self, key):
        return self._slots[key].status

    def mark_dirty(self, key, reason, *, now):
        status = self.status(key)
        status.dirty.add(reason)
        if reason == "source":
            status.next_due = now + self.debounce_seconds
        elif "source" not in status.dirty:
            status.next_due = min(status.next_due, now)

    def pause(self, key):
        self.status(key).paused = True

    def resume(self, key):
        self.status(key).paused = False

    def set_continuous(self, key, continuous):
        self._slots[key].continuous = bool(continuous)

    def set_max_fps(self, key, fps):
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
            raise ValueError("preview max fps must be positive")
        self._slots[key].interval = 1.0 / fps

    def next_delay(self, *, now, idle=0.033):
        """Wake against absolute due times, excluding elapsed render work."""
        if self._suspended:
            return idle
        due = [slot.status.next_due - now for slot in self._slots.values()
               if slot.status.dirty and not slot.status.paused]
        return max(0.002, min(idle, max(0.0, min(due)))) if due else idle

    def suspend(self, reason):
        self._suspended.add(reason)

    def resume_all(self, reason):
        self._suspended.discard(reason)

    def tick(self, *, now, allowed=True, order=None, dependencies=None):
        """Run at most one due producer; retain last good output on failure."""
        if not allowed or self._suspended or not self._slots:
            return None
        keys = (tuple(key for key in order if key in self._slots)
                if order is not None else tuple(self._slots))
        dependencies = dependencies or {}
        if not keys:
            return None
        for offset in range(len(keys)):
            index = (self._cursor + offset) % len(keys)
            key = keys[index]
            slot = self._slots[key]
            status = slot.status
            if status.paused or not status.dirty or now + 1e-12 < status.next_due:
                continue
            upstream = dependencies.get(key, ())
            if any((self._slots[dep].status.error or
                    (self._slots[dep].status.dirty and
                     not self._slots[dep].status.paused and
                     self._slots[dep].status.generation <=
                     slot.dependency_seen.get(dep, 0)))
                   for dep in upstream if dep in self._slots):
                continue
            self._cursor = (index + 1) % len(keys)
            status.dirty.clear()
            try:
                result = slot.produce()
            except ReplayPending as pending:
                status.replay_progress = pending.status
                status.error = ""
                status.dirty.add("replay")
                status.next_due = now + (slot.interval or self.min_interval)
            except Exception as exc:
                status.error = "%s: %s" % (type(exc).__name__, exc)
                status.replay_progress = None
            else:
                status.last_good = result
                status.error = ""
                status.replay_progress = None
                status.generation += 1
                slot.dependency_seen = {
                    dep: self._slots[dep].status.generation for dep in upstream
                    if dep in self._slots
                }
            if slot.continuous and "replay" not in status.dirty:
                status.dirty.add("time")
                status.next_due = now + (slot.interval or self.min_interval)
            return key
        return None
