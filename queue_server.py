"""
queue_server.py
===============
FIFO waiting line that lives inside every station and stage.

Adapted from the hotel-simulation example project, but reshaped for the
festival's conventions:
    - timestamps are floats (minutes from midnight of Day 1),
    - entries are visitor entities (with a `size` attribute),
    - abandonment is supported: an entity can be pulled from the middle
      of the queue when its patience runs out.

Every QueueServer instance tracks its own statistics — waiting times,
time-weighted queue length, and join/serve/abandon counters — so the
station that owns it can answer questions like
"what is the average wait at PhotoStation?" without consulting any
global statistics object.

The simulation's `RunStatistics` still aggregates everything at the end;
this class is the per-queue book-keeping that feeds into it.

Note: the file is named `queue_server.py` (not `queue.py`) on purpose:
Python already ships a standard-library module called `queue`, and
shadowing it would cause subtle import errors elsewhere in the project.
"""

from __future__ import annotations
from typing import List, Optional, Tuple


class QueueServer:
    """
    FIFO waiting line attached to a single station or stage.

    The queue stores ``(entity, arrival_time)`` tuples so it can compute
    each visitor's waiting time at the moment of service.

    Attributes
    ----------
    name : str
        Owner facility's identifier ('EntryGate', 'PhotoStation', ...).
    server_queue : list of (Entity, float)
        The FIFO line. First element is the next to be served.
    waiting_times : list of float
        Waiting time recorded for every served entity.
    queue_change_times : list of float
        Timestamps when the queue length changed.
    queue_lengths : list of int
        Length value AFTER each change in `queue_change_times`.
    total_qlen_time : float
        Time-integrated queue length, updated incrementally.
    n_joined, n_served, n_abandoned : int
        Lifetime counters.
    """

    def __init__(self, name: str):
        self.name: str = name

        # The actual FIFO line
        self.server_queue: List[Tuple] = []

        # Per-entity waiting times (filled when an entity leaves at the head)
        self.waiting_times: List[float] = []

        # Time-weighted queue-length tracking
        self.queue_change_times: List[float] = []
        self.queue_lengths:      List[int]   = []
        self.total_qlen_time:    float       = 0.0

        # Lifetime counters
        self.n_joined:    int = 0
        self.n_served:    int = 0
        self.n_abandoned: int = 0

    # ── Joining / leaving the line ───────────────────────────────────────────

    def add(self, entity, arrival_time: float) -> None:
        """Append an entity to the tail of the queue (FIFO)."""
        self.server_queue.append((entity, arrival_time))
        self.n_joined += 1
        self._record_length_change(arrival_time)

    def pop(self, removing_time: float):
        """
        Remove and return the entity at the head of the queue.

        Records the entity's waiting time and increments `n_served`.
        Returns ``None`` if the queue is empty.
        """
        if not self.server_queue:
            return None
        entity, arrival_time = self.server_queue.pop(0)
        wait = removing_time - arrival_time
        self.waiting_times.append(wait)
        self.n_served += 1
        self._record_length_change(removing_time)
        return entity

    def remove(self, entity, removing_time: float) -> bool:
        """
        Remove a specific entity from anywhere in the queue (abandonment).

        Returns True if the entity was found and removed, False otherwise.
        Abandoned entities are *not* recorded in `waiting_times` because
        they never received service; they are counted in `n_abandoned`.
        """
        for i, (e, _) in enumerate(self.server_queue):
            if e is entity:
                self.server_queue.pop(i)
                self.n_abandoned += 1
                self._record_length_change(removing_time)
                return True
        return False

    def pop_at(self, index: int, removing_time: float):
        """
        Pop the entity at the given index, recording the served-from-queue
        waiting time. Used by stages with first-fit FIFO admission: the
        queue is walked in FIFO order and the first entity whose size
        fits the remaining capacity is admitted. Oversized parties stay
        in line and keep their position for the next admission cycle.

        Returns the entity, or ``None`` if the index is out of range.
        """
        if 0 <= index < len(self.server_queue):
            entity, arrival_time = self.server_queue.pop(index)
            wait = removing_time - arrival_time
            self.waiting_times.append(wait)
            self.n_served += 1
            self._record_length_change(removing_time)
            return entity
        return None

    # ── Inspection ───────────────────────────────────────────────────────────

    def size(self) -> int:
        """Number of entities currently in line."""
        return len(self.server_queue)

    def is_empty(self) -> bool:
        return not self.server_queue

    def peek_first(self):
        """Return the entity at the head without removing it (or None)."""
        return self.server_queue[0][0] if self.server_queue else None

    def contains(self, entity) -> bool:
        """True iff this entity is currently waiting in the line."""
        return any(e is entity for e, _ in self.server_queue)

    def all_waiting_entities(self) -> List:
        """Return every entity currently in the line, in FIFO order."""
        return [e for e, _ in self.server_queue]

    # ── Statistics ───────────────────────────────────────────────────────────

    def avg_waiting_time(self) -> float:
        """Mean waiting time of entities that were actually served."""
        if not self.waiting_times:
            return 0.0
        return sum(self.waiting_times) / len(self.waiting_times)

    def time_avg_length(self, current_time: float) -> float:
        """
        Time-weighted average queue length on
        ``[first_change, current_time]``.

        Equivalent to ``(1/T) * integral_0^T L(t) dt`` where ``L`` is the
        step-function of queue length.
        """
        if not self.queue_change_times:
            return 0.0
        # Close the last interval up to current_time
        last_time = self.queue_change_times[-1]
        last_len  = self.queue_lengths[-1]
        total = self.total_qlen_time + last_len * (current_time - last_time)
        elapsed = current_time - self.queue_change_times[0]
        return total / elapsed if elapsed > 0 else 0.0

    # ── Internals ────────────────────────────────────────────────────────────

    def _record_length_change(self, current_time: float) -> None:
        """
        Accumulate the time-integrated queue length and record the new state.

        Called every time an entity enters or leaves the queue.
        """
        if self.queue_change_times:
            last_time = self.queue_change_times[-1]
            duration  = current_time - last_time
            self.total_qlen_time += self.queue_lengths[-1] * duration
        self.queue_change_times.append(current_time)
        self.queue_lengths.append(self.size())

    # ── Representation ───────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (f"QueueServer(name={self.name!r}, size={self.size()}, "
                f"joined={self.n_joined}, served={self.n_served}, "
                f"abandoned={self.n_abandoned})")
