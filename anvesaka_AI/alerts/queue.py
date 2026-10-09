"""Priority queue service for Anvesaka alert triage.

Enforces strict priority ranking:
  FATAL > CRITICAL > ERROR > WARNING > INFO
With oldest-arrival tie-breaking and thread-safe idempotent deduplication.

Owner: B (Member 1)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Optional

from anvesaka_AI.schemas import Alert, Severity


@dataclass
class QueueItem:
    alert: Alert
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "queued"  # "queued", "analyzing", "triaged", "escalated", "resolved"
    priority_boost: int = 0

    @property
    def effective_rank(self) -> int:
        return self.alert.severity.rank + self.priority_boost

    def sort_key(self) -> tuple[int, datetime]:
        # Negative effective rank so higher severity comes first
        # Oldest timestamp comes first
        return (-self.effective_rank, self.alert.timestamp)


class AlertQueue:
    """Thread-safe priority queue for Alert intake and dispatch."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, QueueItem] = {}

    def push(
        self,
        alert: Alert | dict[str, Any],
        status: str = "queued",
        priority_boost: int = 0,
    ) -> bool:
        """Push an alert into the queue.

        Returns True if a new alert was enqueued, False if updated (idempotent).
        """
        if isinstance(alert, dict):
            alert = Alert.model_validate(alert)

        with self._lock:
            is_new = alert.alert_id not in self._items
            if is_new:
                item = QueueItem(
                    alert=alert,
                    status=status,
                    priority_boost=priority_boost,
                )
                self._items[alert.alert_id] = item
            else:
                existing = self._items[alert.alert_id]
                existing.alert = alert
                existing.status = status
                if priority_boost:
                    existing.priority_boost = priority_boost
            return is_new

    def pop(self) -> Optional[Alert]:
        """Pop the highest priority queued alert."""
        with self._lock:
            queued = [item for item in self._items.values() if item.status == "queued"]
            if not queued:
                return None
            queued.sort(key=lambda i: i.sort_key())
            top = queued[0]
            del self._items[top.alert.alert_id]
            return top.alert

    def peek(self) -> Optional[Alert]:
        """Inspect the highest priority queued alert without removing it."""
        with self._lock:
            queued = [item for item in self._items.values() if item.status == "queued"]
            if not queued:
                return None
            queued.sort(key=lambda i: i.sort_key())
            return queued[0].alert

    def update_status(self, alert_id: str, new_status: str) -> bool:
        """Update the processing status of an alert."""
        with self._lock:
            if alert_id in self._items:
                self._items[alert_id].status = new_status
                return True
            return False

    def boost_priority(self, alert_id: str, boost: int = 1) -> bool:
        """Increase the priority rank of an alert (e.g. if escalating)."""
        with self._lock:
            if alert_id in self._items:
                self._items[alert_id].priority_boost += boost
                return True
            return False

    def remove(self, alert_id: str) -> Optional[Alert]:
        """Remove and return an alert from the queue."""
        with self._lock:
            item = self._items.pop(alert_id, None)
            return item.alert if item else None

    def get(self, alert_id: str) -> Optional[dict[str, Any]]:
        """Get an item by alert_id with its queue position."""
        with self._lock:
            item = self._items.get(alert_id)
            if not item:
                return None
            all_sorted = self.list_items()
            pos = None
            for idx, candidate in enumerate(all_sorted, 1):
                if candidate.alert.alert_id == alert_id:
                    pos = idx
                    break
            data = item.alert.model_dump()
            data["queue_status"] = item.status
            data["queue_position"] = pos
            data["priority_boost"] = item.priority_boost
            return data

    def list_items(
        self,
        status: Optional[str] = None,
        severity: Optional[Severity | str] = None,
    ) -> list[QueueItem]:
        """Get all items in the queue sorted by priority."""
        with self._lock:
            items = list(self._items.values())
            if status is not None:
                items = [i for i in items if i.status == status]
            if severity is not None:
                sev_val = severity.value if isinstance(severity, Severity) else severity
                items = [i for i in items if i.alert.severity.value == sev_val]
            items.sort(key=lambda i: i.sort_key())
            return items

    def list_alerts(
        self,
        status: Optional[str] = None,
        severity: Optional[Severity | str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Get enriched alerts with 1-indexed queue position."""
        with self._lock:
            items = self.list_items(status=status, severity=severity)
            results = []
            for idx, item in enumerate(items, 1):
                data = item.alert.model_dump()
                data["queue_status"] = item.status
                data["queue_position"] = idx if item.status == "queued" else None
                data["priority_boost"] = item.priority_boost
                results.append(data)
            return results[:limit] if limit else results

    def size(self, status: Optional[str] = None) -> int:
        """Count items in the queue (optionally filtered by status)."""
        with self._lock:
            if status is None:
                return len(self._items)
            return sum(1 for item in self._items.values() if item.status == status)

    def is_empty(self) -> bool:
        """Return True if no items are in the queue."""
        with self._lock:
            return len(self._items) == 0

    def clear(self) -> None:
        """Empty the queue."""
        with self._lock:
            self._items.clear()
