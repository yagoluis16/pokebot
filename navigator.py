# pokebot/navigator.py
"""Waypoint navigation: path following with stuck detection."""

from __future__ import annotations
import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from context import get_context

log = logging.getLogger("pokebot.navigator")


@dataclass
class Waypoint:
    x: int
    y: int
    z: int
    name: str = ""
    action: str = "walk"  # walk, wait, use_item, custom
    params: dict = field(default_factory=dict)


class Navigator:
    """
    Waypoint-based navigation. Reads player position from memory,
    issues movement keys to follow the path.
    """

    def __init__(self, resolver=None, ctx=None, bus=None):
        self.ctx = ctx or get_context()
        self.bus = bus
        self.resolver = resolver
        self.waypoints: list[Waypoint] = []
        self.current_index = 0
        self._lock = threading.RLock()
        self._last_pos = (0, 0, 0)
        self._stuck_counter = 0
        self._last_move_time = 0.0
        self._paused = False
        self._path_file = self.ctx.get("cavebot", "waypoints_file", default="waypoints.json")

        # Walk keys
        wk = self.ctx.get("cavebot", "walk_keys", default={
            "north": "Up", "south": "Down", "east": "Right", "west": "Left"
        })
        self._vk_map = self._keys_to_vk(wk)

    def _keys_to_vk(self, wk: dict) -> dict:
        vk_map = {
            "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
            "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
        }
        return {dir_: vk_map.get(key, 0) for dir_, key in wk.items()}

    def load_waypoints(self, path: Optional[str] = None) -> bool:
        path = path or self._path_file
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.waypoints = [Waypoint(**wp) for wp in data.get("waypoints", [])]
            self.current_index = 0
            log.info("Loaded %d waypoints from %s", len(self.waypoints), p)
            return True
        except Exception as exc:
            log.error("Failed to load waypoints from %s: %s", p, exc)
            return False

    def save_waypoints(self, path: Optional[str] = None):
        path = path or self._path_file
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        data = {"waypoints": [wp.__dict__ for wp in self.waypoints]}
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            log.info("Saved %d waypoints to %s", len(self.waypoints), p)
        except Exception as exc:
            log.error("Failed to save waypoints: %s", exc)

    def add_waypoint(self, x: int, y: int, z: int, name: str = "", action: str = "walk"):
        wp = Waypoint(x=x, y=y, z=z, name=name, action=action)
        self.waypoints.append(wp)
        self.save_waypoints()

    def remove_waypoint(self, index: int):
        if 0 <= index < len(self.waypoints):
            self.waypoints.pop(index)
            if self.current_index >= len(self.waypoints):
                self.current_index = max(0, len(self.waypoints) - 1)
            self.save_waypoints()

    def clear_waypoints(self):
        self.waypoints.clear()
        self.current_index = 0
        self.save_waypoints()

    def get_current_target(self) -> Optional[Waypoint]:
        with self._lock:
            if 0 <= self.current_index < len(self.waypoints):
                return self.waypoints[self.current_index]
        return None

    def set_current_index(self, index: int):
        with self._lock:
            self.current_index = max(0, min(index, len(self.waypoints) - 1))

    def get_progress(self) -> dict:
        with self._lock:
            return {
                "total": len(self.waypoints),
                "current": self.current_index + 1 if self.waypoints else 0,
                "target": self.get_current_target().__dict__ if self.get_current_target() else None,
            }

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def get_player_pos(self) -> Optional[tuple[int, int, int]]:
        if not self.resolver:
            return None
        x = self.resolver.read_field("player", "x")
        y = self.resolver.read_field("player", "y")
        z = self.resolver.read_field("player", "z")
        if x is None or y is None or z is None:
            return None
        return (x, y, z)

    def distance_to(self, target: Waypoint, pos: tuple[int, int, int]) -> float:
        dx = target.x - pos[0]
        dy = target.y - pos[1]
        return math.hypot(dx, dy)

    def direction_to(self, target: Waypoint, pos: tuple[int, int, int]) -> Optional[str]:
        dx = target.x - pos[0]
        dy = target.y - pos[1]
        if abs(dx) > abs(dy):
            return "east" if dx > 0 else "west"
        elif dy != 0:
            return "south" if dy > 0 else "north"
        return None

    def execute_step(self, direction: str):
        vk = self._vk_map.get(direction, 0)
        if not vk:
            return
        hold_ms = self.ctx.get("cavebot", "key_hold_ms", default=90)
        self.bus.press_key(vk, hold_ms, module="navigator")

    def check_stuck(self, pos: tuple[int, int, int]) -> bool:
        """Returns True if stuck (position unchanged for threshold)."""
        threshold = self.ctx.get("cavebot", "stuck_threshold_ms", default=1500)
        if pos == self._last_pos:
            if time.monotonic() - self._last_move_time > threshold / 1000.0:
                self._stuck_counter += 1
                return True
        else:
            self._last_pos = pos
            self._last_move_time = time.monotonic()
        return False

    def handle_stuck(self):
        max_retry = self.ctx.get("cavebot", "stuck_retry_count", default=3)
        if self._stuck_counter >= max_retry:
            log.warning("Navigator: max stuck retries reached, pausing")
            self._paused = True
            return
        # Try random direction to unstuck
        import random
        dirs = ["north", "south", "east", "west"]
        random.shuffle(dirs)
        for d in dirs:
            if self._vk_map.get(d, 0):
                self.execute_step(d)
                time.sleep(0.2)
                break
        self.ctx.inc_stat("stuck_recoveries")

    def tick(self):
        if self._paused or self.ctx.is_stopped() or self.ctx.is_paused():
            return
        if not self.waypoints:
            return
        if not self.resolver:
            return

        target = self.get_current_target()
        if not target:
            return

        pos = self.get_player_pos()
        if not pos:
            return

        # Check Z-level
        if pos[2] != target.z:
            log.debug("Z mismatch: player=%d target=%d", pos[2], target.z)
            return

        dist = self.distance_to(target, pos)
        tolerance = self.ctx.get("cavebot", "arrive_tolerance_tiles", default=1)

        if dist <= tolerance:
            # Arrived
            log.info("Arrived at waypoint %d: %s", self.current_index, target.name or f"({target.x},{target.y})")
            self.ctx.inc_stat("waypoints_reached")
            with self._lock:
                self.current_index += 1
                if self.current_index >= len(self.waypoints):
                    self.current_index = 0  # loop
            return

        # Check stuck
        if self.check_stuck(pos):
            self.handle_stuck()
            return

        # Move toward target
        direction = self.direction_to(target, pos)
        if direction:
            self.execute_step(direction)
            max_leg = self.ctx.get("cavebot", "max_seconds_per_leg", default=6)
            # Could add per-leg timeout here

    def creatures_nearby(self, tiles: int = 2) -> bool:
        """Check if creatures within N tiles (pauses cavebot)."""
        # PLACEHOLDER — needs entity list offsets, not yet reversed
        # TODO: reverse entity iteration and position fields, then implement floor/distance checks.
        if not self.resolver:
            return False
        # This requires creature_list block to be resolved
        # Placeholder for when offsets are calibrated
        return False
