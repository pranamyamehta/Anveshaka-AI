"""Event stream and simulator control service for Anvesaka.

Implements an asynchronous Server-Sent Events (SSE) broadcaster and demo alert simulator.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from anvesaka_AI.api.store import _load_raw_alerts

# --------------------------------------------------------------------------- #
# REALTIME EVENT BUS
# --------------------------------------------------------------------------- #
class EventBus:
    """Manages active SSE client connections and event broadcasting."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Register a new SSE client queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unregister a disconnected client queue."""
        self._subscribers.discard(q)

    async def broadcast(self, event: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients."""
        payload = {"event": event, "data": data}
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                self._subscribers.discard(q)


event_bus = EventBus()


# --------------------------------------------------------------------------- #
# DEMO SIMULATOR STATE
# --------------------------------------------------------------------------- #
class SimulatorState:
    """Manages demo alert simulator lifecycle."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.interval_seconds: float = 5.0
        self._task: asyncio.Task | None = None
        self._scenario_index: int = 0

    def start(self, interval_seconds: float = 5.0) -> dict[str, Any]:
        """Start or resume simulator."""
        self.is_running = True
        self.interval_seconds = max(1.0, min(interval_seconds, 60.0))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._simulation_loop())
        return {
            "status": "running",
            "interval_seconds": self.interval_seconds,
            "message": "Alert simulator started.",
        }

    def pause(self) -> dict[str, Any]:
        """Pause simulator."""
        self.is_running = False
        return {
            "status": "paused",
            "message": "Alert simulator paused.",
        }

    async def _simulation_loop(self) -> None:
        """Periodically broadcast simulated alert arrivals."""
        alerts = list(_load_raw_alerts().values())
        if not alerts:
            return

        while self.is_running:
            await asyncio.sleep(self.interval_seconds)
            if not self.is_running:
                break

            alert = alerts[self._scenario_index % len(alerts)]
            self._scenario_index += 1

            # Broadcast alert arrival
            await event_bus.broadcast(
                "alert_received",
                {
                    "alert_id": alert.get("alert_id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "severity": alert.get("severity"),
                    "node_id": alert.get("node_id"),
                    "rack_id": alert.get("rack_id"),
                    "raw_message": alert.get("raw_message"),
                },
            )


simulator = SimulatorState()


# --------------------------------------------------------------------------- #
# SSE STREAM GENERATOR
# --------------------------------------------------------------------------- #
async def sse_event_generator(request_queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events with periodic heartbeat."""
    # Send initial connection frame
    init_frame = {
        "event": "connected",
        "data": {
            "message": "Connected to Anvesaka realtime event stream.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    yield f"event: {init_frame['event']}\ndata: {json.dumps(init_frame['data'])}\n\n"

    try:
        while True:
            try:
                # Wait for next event with a 15-second heartbeat timeout
                msg = await asyncio.wait_for(request_queue.get(), timeout=15.0)
                event_name = msg.get("event", "message")
                data_str = json.dumps(msg.get("data", {}))
                yield f"event: {event_name}\ndata: {data_str}\n\n"
            except asyncio.TimeoutError:
                # Emit heartbeat keep-alive frame
                heartbeat = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "simulator_running": simulator.is_running,
                }
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        event_bus.unsubscribe(request_queue)
